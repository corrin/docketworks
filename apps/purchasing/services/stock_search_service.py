"""Stock search: Postgres FTS candidate retrieval plus a domain-aware re-rank.

The scoring model recognizes the merchant shorthand operators use
("50x50 SHS galv", "3mm s/s sht"), so the ranker expands aliases, extracts
dimensions/thicknesses and rewards structured-field hits.

A separate ``search_stock`` typeahead helper is deliberately absent because the
frontend uses the paginated endpoint; another helper would create a second
entry point into one concept (ADR 0039).
"""

import logging
import math
import re
from dataclasses import dataclass
from typing import Final, TypedDict

from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector
from django.db.models import Count, Q, QuerySet
from django.db.models.expressions import CombinedExpression

from apps.job.models.costing import CostLine
from apps.purchasing.models import Stock
from apps.purchasing.services.stock_service import StockItemData, stock_item_data

logger = logging.getLogger(__name__)

MAX_SEARCH_QUERY_LENGTH: Final = 512
MAX_PAGE_SIZE: Final = 100

ALLOWED_SORT_FIELDS: Final[dict[str, str]] = {
    "description": "description",
    "item_code": "item_code",
    "quantity": "quantity",
    "unit_cost": "unit_cost",
    "unit_revenue": "unit_revenue",
    "metal_type": "metal_type",
    "alloy": "alloy",
    "specifics": "specifics",
    "location": "location",
    "date": "date",
}

PHRASE_RE = re.compile(r'"([^"]+)"')
NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
TOKEN_RE = re.compile(r"[a-z0-9.]+")
# The separator _expand_aliases() normalises dimension pairs to; never a term.
DIMENSION_JOINER = "x"
FRACTION_RE = re.compile(r'(\d+)\s*/\s*(\d+)(?="|\b)')
# The multiplication sign in these patterns is deliberate: operators paste
# dimensions straight out of supplier PDFs, which use it instead of "x".
DIMENSION_PAIR_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*[x×]\s*(\d+(?:\.\d+)?)",  # noqa: RUF001
    re.IGNORECASE,
)
DIMENSION_TRIPLE_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*[x×]\s*(\d+(?:\.\d+)?)\s*[x×]\s*(\d+(?:\.\d+)?)",  # noqa: RUF001
    re.IGNORECASE,
)
THICKNESS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*mm\b", re.IGNORECASE)

ALIAS_REPLACEMENTS: Final[dict[str, str]] = {
    "galv": "galvanised",
    "galv.": "galvanised",
    "galvanized": "galvanised",
    "ss": "stainless",
    "s/s": "stainless",
    "sht": "sheet",
    "plt": "plate",
    "dia": "diameter",
}
FORM_PATTERNS: Final[dict[str, tuple[str, ...]]] = {
    "round_bar": ("round bar", "dia round bar", "diameter round bar"),
    "flat_bar": ("flat bar",),
    "washer": ("washer",),
    "sheet": ("sheet",),
    "plate": ("plate",),
    "tube": ("tube",),
    "rhs": ("rhs",),
    "shs": ("shs",),
}

STOCK_SEARCH_VECTOR = (
    SearchVector("description", weight="A", config="english")
    + SearchVector("item_code", weight="A", config="english")
    + SearchVector("metal_type", weight="B", config="english")
    + SearchVector("alloy", weight="B", config="english")
    + SearchVector("specifics", weight="B", config="english")
    + SearchVector("location", weight="C", config="english")
)


@dataclass(frozen=True, slots=True)
class SearchFeatures:
    """The normalised shape of a query or a stock row, ready to score."""

    normalized_text: str
    tokens: frozenset[str]
    numeric_tokens: frozenset[str]
    numeric_values: tuple[float, ...]
    thicknesses: tuple[float, ...]
    dimension_pairs: tuple[tuple[float, float], ...]
    phrases: tuple[str, ...]
    forms: frozenset[str]


class StockSearchPage(TypedDict):
    """The paginated stock-search envelope."""

    results: list[StockItemData]
    count: int
    page: int
    page_size: int
    total_pages: int


def apply_text_search(
    queryset: QuerySet[Stock], query: str, vector: SearchVector | CombinedExpression
) -> QuerySet[Stock]:
    """Rank and filter ``queryset`` by Postgres websearch FTS.

    The match filter is the ``@@`` operator, not ``search_rank__gt=0``:
    ``ts_rank`` returns a tiny non-zero epsilon for non-matching documents, so
    the rank filter would return every row in the table. (v1
    ``apps/workflow/services/search.py``; purchasing is v2's first consumer, so
    it lives here until a second domain app needs it.)
    """
    search_query = SearchQuery(query, search_type="websearch", config="english")
    return queryset.annotate(
        search_doc=vector, search_rank=SearchRank(vector, search_query)
    ).filter(search_doc=search_query)


def _normalize_search_query(query: str) -> str:
    normalized = query.strip()
    if len(normalized) > MAX_SEARCH_QUERY_LENGTH:
        raise ValueError("Search query too long.")
    return normalized


def _normalize_number(value: float) -> tuple[str, ...]:
    integral = round(value)
    if math.isclose(value, integral, abs_tol=1e-6):
        return (str(integral), f"{integral}.0")
    return (f"{value:.3f}".rstrip("0").rstrip("."),)


def _expand_aliases(text: str) -> str:
    lowered = text.lower()
    lowered = FRACTION_RE.sub(
        lambda match: f"{(float(match.group(1)) / float(match.group(2))):.4f}", lowered
    )
    for src, dst in ALIAS_REPLACEMENTS.items():
        lowered = re.sub(rf"\b{re.escape(src)}\b", dst, lowered)
    lowered = re.sub(r"([0-9])([a-z])", r"\1 \2", lowered)
    lowered = re.sub(r"(?<=\d)[x×](?=\d)", " x ", lowered)  # noqa: RUF001
    return re.sub(r"\s+", " ", lowered).strip()


def _extract_forms(text: str) -> frozenset[str]:
    return frozenset(
        form for form, patterns in FORM_PATTERNS.items() if any(p in text for p in patterns)
    )


def _extract_dimension_pairs(text: str) -> tuple[tuple[float, float], ...]:
    pairs: set[tuple[float, float]] = set()
    for match in DIMENSION_TRIPLE_RE.finditer(text):
        _, first, second = match.groups()
        low, high = sorted((float(first), float(second)))
        pairs.add((low, high))
    for match in DIMENSION_PAIR_RE.finditer(text):
        first, second = match.groups()
        low, high = sorted((float(first), float(second)))
        pairs.add((low, high))
    return tuple(sorted(pairs))


def _extract_thicknesses(text: str) -> tuple[float, ...]:
    thicknesses = {float(match.group(1)) for match in THICKNESS_RE.finditer(text)}
    for match in DIMENSION_TRIPLE_RE.finditer(text):
        thicknesses.add(float(match.group(1)))
    return tuple(sorted(thicknesses))


def _build_features(text: str) -> SearchFeatures:
    normalized_text = _expand_aliases(text)
    numeric_tokens: set[str] = set()
    numeric_values: list[float] = []
    for raw in NUMBER_RE.findall(normalized_text):
        value = float(raw)
        numeric_values.append(value)
        numeric_tokens.update(_normalize_number(value))
    return SearchFeatures(
        normalized_text=normalized_text,
        tokens=frozenset(TOKEN_RE.findall(normalized_text)),
        numeric_tokens=frozenset(numeric_tokens),
        numeric_values=tuple(numeric_values),
        thicknesses=_extract_thicknesses(normalized_text),
        dimension_pairs=_extract_dimension_pairs(normalized_text),
        phrases=tuple(_expand_aliases(phrase) for phrase in PHRASE_RE.findall(text)),
        forms=_extract_forms(normalized_text),
    )


def _build_stock_text(stock: Stock) -> str:
    parts = (
        stock.description,
        stock.item_code,
        stock.metal_type,
        stock.alloy,
        stock.specifics,
        stock.location,
    )
    return " ".join(part for part in parts if part)


def _usage_counts_by_item_code() -> dict[str, int]:
    rows = (
        CostLine.objects.filter(kind="material")
        .exclude(meta__item_code__isnull=True)
        .exclude(meta__item_code="")
        .values_list("meta__item_code")
        .annotate(count=Count("id"))
    )
    return {item_code: count for item_code, count in rows if item_code}


def _dimension_similarity(
    query_dims: tuple[float, float], stock_dims: tuple[float, float]
) -> float:
    worst = max(abs(query_dims[0] - stock_dims[0]), abs(query_dims[1] - stock_dims[1]))
    if worst < 0.001:
        return 1.0
    if worst <= 50:
        return 0.8
    if worst <= 100:
        return 0.45
    return 0.0


def _thickness_similarity(query_value: float, stock_value: float) -> float:
    diff = abs(query_value - stock_value)
    if diff < 0.001:
        return 1.0
    if diff <= 0.11:
        return 0.9
    if diff <= 0.25:
        return 0.55
    return 0.0


def _generic_number_similarity(query_value: float, stock_values: tuple[float, ...]) -> float:
    best = 0.0
    for stock_value in stock_values:
        diff = abs(query_value - stock_value)
        if diff < 0.001:
            return 1.0
        if query_value >= 100:
            if diff <= 50:
                best = max(best, 0.55)
            elif diff <= 100:
                best = max(best, 0.25)
    return best


def _token_score(query: SearchFeatures, stock: SearchFeatures) -> float:
    score = 0.0
    for token in query.tokens:
        if token in query.numeric_tokens or token == DIMENSION_JOINER:
            continue
        if token in stock.tokens:
            score += 7.0
        elif token in stock.normalized_text:
            score += 4.0
    for phrase in query.phrases:
        if phrase and phrase in stock.normalized_text:
            score += 20.0
    return score


def _form_score(query: SearchFeatures, stock: SearchFeatures) -> float:
    if not query.forms:
        return 0.0
    shared = query.forms & stock.forms
    if shared:
        return 28.0 * len(shared)
    if stock.forms:
        return -18.0
    return 0.0


def _structured_field_score(stock: Stock, query: SearchFeatures) -> float:
    score = 0.0
    item_code_text = _expand_aliases(stock.item_code or "")
    alloy_tokens = set(TOKEN_RE.findall(_expand_aliases(stock.alloy or "")))
    for token in query.tokens | query.numeric_tokens:
        if token in alloy_tokens:
            score += 16.0
        if token and token in item_code_text:
            score += 10.0
    return score


def _measurement_score(query: SearchFeatures, stock: SearchFeatures) -> float:  # noqa: C901 -- Ordered measurement tiers are clearer as one scoring ladder.
    score = 0.0
    if query.dimension_pairs:
        best = 0.0
        for query_dims in query.dimension_pairs:
            for stock_dims in stock.dimension_pairs:
                best = max(best, _dimension_similarity(query_dims, stock_dims))
        score += best * 18.0
    if query.thicknesses:
        best = 0.0
        for query_thickness in query.thicknesses:
            for stock_thickness in stock.thicknesses:
                best = max(best, _thickness_similarity(query_thickness, stock_thickness))
        score += best * 16.0

    consumed: set[str] = set()
    for thickness in query.thicknesses:
        consumed.update(_normalize_number(thickness))
    for first, second in query.dimension_pairs:
        consumed.update(_normalize_number(first))
        consumed.update(_normalize_number(second))

    for raw in query.numeric_tokens - consumed:
        query_value = float(raw)
        if query.forms & {"round_bar", "flat_bar"} and query_value < 100 and stock.thicknesses:
            score += _thickness_similarity(query_value, stock.thicknesses[0]) * 12.0
        score += _generic_number_similarity(query_value, stock.numeric_values) * 10.0
    return score


def _matches(query: SearchFeatures, stock: SearchFeatures) -> bool:
    if not query.phrases:
        return True
    return any(phrase in stock.normalized_text for phrase in query.phrases)


def _score_stock(stock: Stock, query: SearchFeatures, usage_counts: dict[str, int]) -> float:
    stock_features = _build_features(_build_stock_text(stock))
    if not _matches(query, stock_features):
        return 0.0
    score = _token_score(query, stock_features)
    score += _form_score(query, stock_features)
    score += _structured_field_score(stock, query)
    score += _measurement_score(query, stock_features)
    if stock.item_code:
        score += math.log1p(usage_counts.get(stock.item_code, 0))
    return score


def _candidate_numeric_terms(text: str) -> set[str]:
    return {
        raw for raw in NUMBER_RE.findall(_expand_aliases(text)) if len(raw.replace(".", "")) >= 3
    }


def _candidate_queryset(query: str) -> QuerySet[Stock]:
    normalized_query = _normalize_search_query(query)
    expanded_query = _expand_aliases(normalized_query)
    queryset = Stock.objects.filter(is_active=True)

    candidate_ids = set(
        apply_text_search(queryset, normalized_query, STOCK_SEARCH_VECTOR).values_list(
            "id", flat=True
        )
    )
    if expanded_query != normalized_query:
        candidate_ids.update(
            apply_text_search(queryset, expanded_query, STOCK_SEARCH_VECTOR).values_list(
                "id", flat=True
            )
        )
    numeric_terms = _candidate_numeric_terms(expanded_query)
    if numeric_terms:
        numeric_filter = Q()
        for term in numeric_terms:
            numeric_filter |= Q(description__icontains=term)
            numeric_filter |= Q(item_code__icontains=term)
            numeric_filter |= Q(alloy__icontains=term)
            numeric_filter |= Q(specifics__icontains=term)
        candidate_ids.update(queryset.filter(numeric_filter).values_list("id", flat=True))

    if candidate_ids:
        return queryset.filter(id__in=candidate_ids)
    return queryset


def _sorted_stock_matches(query: str) -> tuple[list[Stock], dict[str, int]]:
    normalized = _normalize_search_query(query)
    usage_counts = _usage_counts_by_item_code()
    query_features = _build_features(normalized)
    scored: list[tuple[float, Stock]] = []
    for stock in _candidate_queryset(normalized):
        score = _score_stock(stock, query_features, usage_counts)
        if score > 0:
            scored.append((score, stock))
    scored.sort(key=lambda item: (-item[0], item[1].description.lower(), item[1].item_code or ""))
    return [stock for _, stock in scored], usage_counts


def _serialize(items: list[Stock], usage_counts: dict[str, int]) -> list[StockItemData]:
    return [
        stock_item_data(stock, times_used=usage_counts.get(stock.item_code or "", 0))
        for stock in items
    ]


def list_stock(
    *,
    query: str | None = None,
    page: int = 1,
    page_size: int = 50,
    sort_by: str = "description",
    sort_dir: str = "asc",
) -> StockSearchPage:
    """Paginated stock listing, optionally filtered and ranked by ``query``."""
    sort_field = ALLOWED_SORT_FIELDS.get(sort_by, "description")
    if sort_dir.lower() == "desc":
        sort_field = f"-{sort_field}"
    page_size = max(1, min(page_size, MAX_PAGE_SIZE))
    offset = (page - 1) * page_size

    if query:
        logger.info(
            "Stock paginated search query=%r page=%s page_size=%s sort_by=%s sort_dir=%s",
            query,
            page,
            page_size,
            sort_by,
            sort_dir,
        )
        ranked, usage_counts = _sorted_stock_matches(query)
        total_count = len(ranked)
        items = ranked[offset : offset + page_size]
    else:
        queryset = Stock.objects.filter(is_active=True)
        total_count = queryset.count()
        items = list(queryset.order_by(sort_field)[offset : offset + page_size])
        usage_counts = _usage_counts_by_item_code()

    total_pages = (total_count + page_size - 1) // page_size
    if query:
        logger.info(
            "Stock paginated search completed query=%r count=%s page=%s total_pages=%s",
            query,
            total_count,
            page,
            total_pages,
        )
    return {
        "results": _serialize(items, usage_counts),
        "count": total_count,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }
