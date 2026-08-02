"""Supplier lookup for the purchase-order supplier picker.

Ported from v1 ``apps/purchasing/services/supplier_search_service.py``. Unlike
company search this is a name/alias matcher with a recent-purchase boost: the
PO screen wants the supplier you actually buy from, spelled the way the yard
spells it ("A&G", "PSL", "Steel & Tube").
"""

import logging
import math
import re
from dataclasses import dataclass
from datetime import timedelta
from difflib import SequenceMatcher
from typing import TYPE_CHECKING, Final, TypedDict, cast

from django.db.models import Count, Q
from django.utils import timezone

from apps.company.models import Company, ContactMethod, SupplierSearchAlias

if TYPE_CHECKING:
    from django_stubs_ext import WithAnnotations

logger = logging.getLogger(__name__)

MAX_PAGE_SIZE: Final = 100
MAX_SEARCH_QUERY_LENGTH: Final = 255
RECENT_PURCHASE_WINDOW_DAYS: Final = 730
MIN_NAME_SCORE: Final = 250.0

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOP_WORDS: Final[frozenset[str]] = frozenset({"and", "the", "limited", "ltd", "company", "co"})


class SupplierAnnotations(TypedDict):
    """Queryset annotations ``list_suppliers`` adds; not Company model fields."""

    recent_purchase_count: int
    primary_phone: str


if TYPE_CHECKING:
    # Evaluated only by the type checker (annotation quoted at use sites), so
    # the dev-only django_stubs_ext dependency is never imported at runtime.
    _AnnotatedSupplier = WithAnnotations[Company, SupplierAnnotations]


class SupplierSearchResultData(TypedDict):
    """v1 SupplierSearchResultSerializer row."""

    id: str
    name: str
    email: str
    phone: str
    address: str
    is_account_customer: bool
    is_supplier: bool
    allow_jobs: bool
    xero_contact_id: str
    last_invoice_date: None
    total_spend: str
    recent_purchase_count: int


class SupplierSearchPage(TypedDict):
    """v1 SupplierSearchResponseSerializer envelope."""

    results: list[SupplierSearchResultData]
    count: int
    page: int
    page_size: int
    total_pages: int


@dataclass(frozen=True, slots=True)
class _CandidateScore:
    company: "_AnnotatedSupplier"
    score: float
    name_score: float
    recent_purchase_count: int


def annotated_supplier(company: Company) -> "_AnnotatedSupplier":
    """Vouch that the search annotations are present on a fetched Company."""
    missing = {"recent_purchase_count", "primary_phone"} - set(company.__dict__)
    if missing:
        raise RuntimeError(f"supplier queryset is missing annotations: {sorted(missing)}")
    return cast("_AnnotatedSupplier", company)


def normalize_supplier_phrase(value: str) -> str:
    """Normalise names/aliases into punctuation-insensitive, stop-word-free tokens."""
    normalized = value.lower().replace("&", " and ")
    tokens = _TOKEN_RE.findall(normalized)
    return " ".join(token for token in tokens if token not in _STOP_WORDS)


def _normalize_literal_phrase(value: str) -> str:
    return " ".join(_TOKEN_RE.findall(value.lower().replace("&", " and ")))


def _literal_query_variants(query: str) -> list[str]:
    variants = [query]
    expanded = query.replace("&", " and ")
    if expanded != query:
        variants.append(expanded)
    tokens = _TOKEN_RE.findall(query.lower())
    if len(tokens) == 2 and all(len(token) == 1 for token in tokens):
        # "A&G" is filed as "G&A" about as often as not.
        variants.append(f"{tokens[1]}&{tokens[0]}")
        variants.append(f"{tokens[1]} and {tokens[0]}")
    return list(dict.fromkeys(variant for variant in variants if variant))


def _compact(value: str) -> str:
    return value.replace(" ", "")


def _phrase_match_score(candidate_norm: str, query_norm: str) -> float:  # noqa: PLR0911 -- one return per match tier (v1 scoring ladder)
    if not candidate_norm or not query_norm:
        return 0.0
    compact_candidate = _compact(candidate_norm)
    compact_query = _compact(query_norm)
    if not compact_candidate or not compact_query:
        return 0.0
    if candidate_norm == query_norm:
        return 1000.0
    if candidate_norm.startswith(f"{query_norm} "):
        return 920.0
    if compact_candidate.startswith(compact_query):
        return 900.0
    if f" {query_norm} " in f" {candidate_norm} ":
        return 760.0
    if compact_query in compact_candidate:
        return 700.0
    return SequenceMatcher(None, candidate_norm, query_norm).ratio() * 500.0


def _name_match_score(candidate_terms: list[str], query_norm: str) -> float:
    return max((_phrase_match_score(term, query_norm) for term in candidate_terms), default=0.0)


def _contains_all_tokens_q(field_name: str, tokens: list[str]) -> Q:
    meaningful = [token for token in tokens if len(token) > 1]
    if not meaningful:
        return Q(pk__in=[])
    query = Q()
    for token in meaningful:
        query &= Q(**{f"{field_name}__icontains": token})
    return query


def _literal_variants_q(field_name: str, query: str) -> Q:
    filter_q = Q()
    for variant in _literal_query_variants(query):
        filter_q |= Q(**{f"{field_name}__icontains": variant})
    return filter_q


def _supplier_candidate_filter(query: str, query_norm: str) -> Q:
    tokens = query_norm.split()
    name_filter = _literal_variants_q("name", query) | _contains_all_tokens_q("name", tokens)
    alias_filter = Q(supplier_search_aliases__is_active=True) & (
        _literal_variants_q("supplier_search_aliases__alias", query)
        | _contains_all_tokens_q("supplier_search_aliases__alias", tokens)
    )
    return name_filter | alias_filter


def _format_supplier(score: _CandidateScore) -> SupplierSearchResultData:
    company = score.company
    return {
        "id": str(company.id),
        "name": company.name,
        "email": company.email or "",
        "phone": company.primary_phone,
        "address": company.address or "",
        "is_account_customer": company.is_account_customer,
        "is_supplier": company.is_supplier,
        "allow_jobs": company.allow_jobs,
        "xero_contact_id": company.xero_contact_id or "",
        # v1 never populated these two; the PO picker does not use them and
        # the invoice rollup they would need is a Phase 4 (Xero) read.
        "last_invoice_date": None,
        "total_spend": "$0.00",
        "recent_purchase_count": score.recent_purchase_count,
    }


def _score_by_recent_purchases(company: Company) -> _CandidateScore:
    """Rank an unfiltered listing by how recently/often we have bought from them."""
    annotated = annotated_supplier(company)
    return _CandidateScore(
        company=annotated,
        score=float(annotated.recent_purchase_count),
        name_score=0.0,
        recent_purchase_count=annotated.recent_purchase_count,
    )


def _score_candidates(companies: list[Company], score_query_norm: str) -> list[_CandidateScore]:
    aliases_by_company_id: dict[object, list[SupplierSearchAlias]] = {
        company.id: [] for company in companies
    }
    for alias in SupplierSearchAlias.objects.filter(
        is_active=True, company_id__in=list(aliases_by_company_id)
    ).only("id", "company_id", "alias"):
        aliases_by_company_id[alias.company_id].append(alias)

    scores: list[_CandidateScore] = []
    for company in companies:
        annotated = annotated_supplier(company)
        candidate_terms = [
            normalize_supplier_phrase(company.name),
            _normalize_literal_phrase(company.name),
        ]
        for alias in aliases_by_company_id[company.id]:
            candidate_terms.append(normalize_supplier_phrase(alias.alias))
            candidate_terms.append(_normalize_literal_phrase(alias.alias))

        name_score = _name_match_score(candidate_terms, score_query_norm)
        if name_score < MIN_NAME_SCORE:
            continue
        recent = annotated.recent_purchase_count
        scores.append(
            _CandidateScore(
                company=annotated,
                score=name_score + min(recent, 50) * 5.0,
                name_score=name_score,
                recent_purchase_count=recent,
            )
        )
    return scores


def list_suppliers(*, query: str | None, page: int = 1, page_size: int = 50) -> SupplierSearchPage:
    """List supplier candidates for the PO supplier picker."""
    if query is not None and len(query) > MAX_SEARCH_QUERY_LENGTH:
        raise ValueError(f"Search query must be {MAX_SEARCH_QUERY_LENGTH} characters or fewer")

    page = max(1, page)
    page_size = max(1, min(page_size, MAX_PAGE_SIZE))
    offset = (page - 1) * page_size
    cutoff = timezone.localdate() - timedelta(days=RECENT_PURCHASE_WINDOW_DAYS)

    queryset = (
        Company.objects.filter(xero_archived=False, merged_into__isnull=True)
        .annotate(
            recent_purchase_count=Count(
                "purchase_orders",
                filter=Q(purchase_orders__order_date__gte=cutoff)
                & ~Q(purchase_orders__status="deleted"),
                distinct=True,
            ),
            primary_phone=ContactMethod.primary_phone_annotation(owner="company", outer_ref="pk"),
        )
        .defer("raw_json")
    )

    if not query:
        total_count = queryset.count()
        scores = [
            _score_by_recent_purchases(company)
            for company in queryset.order_by("-recent_purchase_count", "name")[
                offset : offset + page_size
            ]
        ]
    else:
        query_norm = normalize_supplier_phrase(query)
        score_query_norm = query_norm or _normalize_literal_phrase(query)
        if not score_query_norm:
            # Punctuation-only searches carry no meaningful supplier query.
            scores = []
            total_count = 0
        else:
            candidates = list(
                queryset.filter(_supplier_candidate_filter(query, query_norm)).distinct()
            )
            scores = _score_candidates(candidates, score_query_norm)
            scores.sort(
                key=lambda score: (
                    -score.score,
                    -score.name_score,
                    -score.recent_purchase_count,
                    score.company.name.lower(),
                )
            )
            total_count = len(scores)
            scores = scores[offset : offset + page_size]

    return {
        "results": [_format_supplier(score) for score in scores],
        "count": total_count,
        "page": page,
        "page_size": page_size,
        "total_pages": math.ceil(total_count / page_size) if total_count else 0,
    }
