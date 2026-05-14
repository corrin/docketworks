"""Supplier search service for purchase-order supplier lookup."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import timedelta
from difflib import SequenceMatcher
from typing import Any

from django.db.models import Count, Prefetch, Q
from django.utils import timezone

from apps.client.models import Client, SupplierSearchAlias

MAX_PAGE_SIZE = 100
MAX_SEARCH_QUERY_LENGTH = 255
RECENT_PURCHASE_WINDOW_DAYS = 730

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOP_WORDS = {"and", "the", "limited", "ltd", "company", "co"}


@dataclass(frozen=True)
class _CandidateScore:
    client: Client
    score: float
    name_score: float
    recent_purchase_count: int


def normalize_supplier_phrase(value: str) -> str:
    """Normalize supplier names/aliases into punctuation-insensitive tokens."""
    normalized = value.lower().replace("&", " and ")
    tokens = [token for token in _TOKEN_RE.findall(normalized)]
    meaningful_tokens = [token for token in tokens if token not in _STOP_WORDS]
    return " ".join(meaningful_tokens)


def _compact(value: str) -> str:
    return value.replace(" ", "")


def _phrase_match_score(candidate_norm: str, query_norm: str) -> float:
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
    best = 0.0
    for term in candidate_terms:
        best = max(best, _phrase_match_score(term, query_norm))
    return best


def _format_supplier(client: Client, score: _CandidateScore) -> dict[str, Any]:
    return {
        "id": str(client.id),
        "name": client.name,
        "email": client.email or "",
        "phone": client.phone or "",
        "address": client.address or "",
        "is_account_customer": client.is_account_customer,
        "is_supplier": client.is_supplier,
        "allow_jobs": client.allow_jobs,
        "xero_contact_id": client.xero_contact_id or "",
        "last_invoice_date": None,
        "total_spend": "$0.00",
        "recent_purchase_count": score.recent_purchase_count,
    }


def list_suppliers(
    *,
    query: str | None,
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    """List supplier candidates for purchase-order supplier lookup."""
    if query is not None and len(query) > MAX_SEARCH_QUERY_LENGTH:
        raise ValueError(
            f"Search query must be {MAX_SEARCH_QUERY_LENGTH} characters or fewer"
        )

    page = max(1, page)
    page_size = max(1, min(page_size, MAX_PAGE_SIZE))
    cutoff = timezone.localdate() - timedelta(days=RECENT_PURCHASE_WINDOW_DAYS)

    queryset = (
        Client.objects.filter(xero_archived=False, merged_into__isnull=True)
        .annotate(
            recent_purchase_count=Count(
                "purchase_orders",
                filter=Q(purchase_orders__order_date__gte=cutoff)
                & ~Q(purchase_orders__status="deleted"),
                distinct=True,
            )
        )
        .defer("raw_json")
        .only(
            "id",
            "name",
            "email",
            "phone",
            "address",
            "is_account_customer",
            "is_supplier",
            "allow_jobs",
            "xero_contact_id",
        )
        .prefetch_related(
            Prefetch(
                "supplier_search_aliases",
                queryset=SupplierSearchAlias.objects.filter(is_active=True).only(
                    "id", "client_id", "alias"
                ),
                to_attr="active_supplier_search_aliases",
            )
        )
    )

    if not query:
        total_count = queryset.count()
        offset = (page - 1) * page_size
        suppliers = queryset.order_by("-recent_purchase_count", "name")[
            offset : offset + page_size
        ]
        scores = [
            _CandidateScore(
                client=supplier,
                score=float(supplier.recent_purchase_count),
                name_score=0.0,
                recent_purchase_count=supplier.recent_purchase_count,
            )
            for supplier in suppliers
        ]
    else:
        query_norm = normalize_supplier_phrase(query)
        scores = []
        for supplier in queryset:
            candidate_terms = [normalize_supplier_phrase(supplier.name)]
            candidate_terms.extend(
                normalize_supplier_phrase(alias.alias)
                for alias in supplier.active_supplier_search_aliases
            )
            name_score = _name_match_score(candidate_terms, query_norm)
            if name_score < 250.0:
                continue

            recent_purchase_count = supplier.recent_purchase_count
            purchase_boost = min(recent_purchase_count, 50) * 5.0
            scores.append(
                _CandidateScore(
                    client=supplier,
                    score=name_score + purchase_boost,
                    name_score=name_score,
                    recent_purchase_count=recent_purchase_count,
                )
            )

        scores.sort(
            key=lambda score: (
                -score.score,
                -score.name_score,
                -score.recent_purchase_count,
                score.client.name.lower(),
            )
        )
        total_count = len(scores)
        offset = (page - 1) * page_size
        scores = scores[offset : offset + page_size]

    total_pages = math.ceil(total_count / page_size) if total_count else 0
    return {
        "results": [_format_supplier(score.client, score) for score in scores],
        "count": total_count,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }
