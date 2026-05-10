"""Stock search service."""

import logging
import math
import re
from typing import Any, Dict, Iterable, List

from django.db.models import Count

from apps.job.models.costing import CostLine
from apps.purchasing.models import Stock
from apps.purchasing.serializers import StockItemSerializer
from apps.workflow.exceptions import AlreadyLoggedException
from apps.workflow.services.error_persistence import persist_and_raise

logger = logging.getLogger(__name__)

MAX_SEARCH_QUERY_LENGTH = 512

ALLOWED_SORT_FIELDS = {
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
FRACTION_RE = re.compile(r'(\d+)\s*/\s*(\d+)(?="|\b)')
DIMENSION_PAIR_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*[x×]\s*(\d+(?:\.\d+)?)", re.IGNORECASE
)
DIMENSION_TRIPLE_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*[x×]\s*(\d+(?:\.\d+)?)\s*[x×]\s*(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
THICKNESS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*mm\b", re.IGNORECASE)
ALIAS_REPLACEMENTS = {
    "galv": "galvanised",
    "galv.": "galvanised",
    "galvanized": "galvanised",
    "ss": "stainless",
    "s/s": "stainless",
    "sht": "sheet",
    "plt": "plate",
    "dia": "diameter",
}
FORM_PATTERNS = {
    "round_bar": ("round bar", "dia round bar", "diameter round bar"),
    "flat_bar": ("flat bar",),
    "washer": ("washer",),
    "sheet": ("sheet",),
    "plate": ("plate",),
    "tube": ("tube",),
    "rhs": ("rhs",),
    "shs": ("shs",),
}


def _normalize_search_query(query: str) -> str:
    normalized = query.strip()
    if len(normalized) > MAX_SEARCH_QUERY_LENGTH:
        raise ValueError("Search query too long.")
    return normalized


def _normalize_number(value: float) -> tuple[str, ...]:
    integral = int(round(value))
    if math.isclose(value, integral, abs_tol=1e-6):
        return (str(integral), f"{integral}.0")
    normalized = f"{value:.3f}".rstrip("0").rstrip(".")
    return (normalized,)


def _expand_aliases(text: str) -> str:
    lowered = text.lower()
    lowered = FRACTION_RE.sub(
        lambda match: f"{(float(match.group(1)) / float(match.group(2))):.4f}",
        lowered,
    )
    for src, dst in ALIAS_REPLACEMENTS.items():
        lowered = re.sub(rf"\b{re.escape(src)}\b", dst, lowered)
    lowered = re.sub(r"([0-9])([a-z])", r"\1 \2", lowered)
    lowered = re.sub(r"(?<=\d)[x×](?=\d)", " x ", lowered)
    lowered = re.sub(r"\s+", " ", lowered).strip()
    return lowered


def _extract_forms(text: str) -> set[str]:
    forms: set[str] = set()
    for form_name, patterns in FORM_PATTERNS.items():
        if any(pattern in text for pattern in patterns):
            forms.add(form_name)
    return forms


def _extract_dimension_pairs(text: str) -> list[tuple[float, float]]:
    pairs: set[tuple[float, float]] = set()
    for match in DIMENSION_TRIPLE_RE.finditer(text):
        _, first, second = match.groups()
        dims = tuple(sorted((float(first), float(second))))
        pairs.add(dims)
    for match in DIMENSION_PAIR_RE.finditer(text):
        first, second = match.groups()
        dims = tuple(sorted((float(first), float(second))))
        pairs.add(dims)
    return sorted(pairs)


def _extract_thicknesses(text: str) -> list[float]:
    thicknesses = {float(match.group(1)) for match in THICKNESS_RE.finditer(text)}
    for match in DIMENSION_TRIPLE_RE.finditer(text):
        thicknesses.add(float(match.group(1)))
    return sorted(thicknesses)


def _extract_numeric_tokens(text: str) -> tuple[set[str], list[float]]:
    tokens: set[str] = set()
    values: list[float] = []
    for raw in NUMBER_RE.findall(text):
        value = float(raw)
        values.append(value)
        tokens.update(_normalize_number(value))
    return tokens, values


def _build_features(text: str) -> dict[str, Any]:
    normalized_text = _expand_aliases(text)
    numeric_tokens, numeric_values = _extract_numeric_tokens(normalized_text)
    return {
        "normalized_text": normalized_text,
        "tokens": set(TOKEN_RE.findall(normalized_text)),
        "numeric_tokens": numeric_tokens,
        "numeric_values": numeric_values,
        "thicknesses": _extract_thicknesses(normalized_text),
        "dimension_pairs": _extract_dimension_pairs(normalized_text),
        "phrases": [_expand_aliases(phrase) for phrase in PHRASE_RE.findall(text)],
        "forms": _extract_forms(normalized_text),
    }


def _build_stock_text(stock: Stock) -> str:
    parts = [
        stock.description or "",
        stock.item_code or "",
        stock.metal_type or "",
        stock.alloy or "",
        stock.specifics or "",
        stock.location or "",
    ]
    return " ".join(part for part in parts if part)


def _usage_counts_by_item_code() -> dict[str, int]:
    rows = (
        CostLine.objects.filter(kind="material")
        .exclude(meta__item_code__isnull=True)
        .exclude(meta__item_code="")
        .values_list("meta__item_code")
        .annotate(c=Count("id"))
    )
    return {item_code: count for item_code, count in rows if item_code}


def _dimension_similarity(
    query_dims: tuple[float, float], stock_dims: tuple[float, float]
) -> float:
    diffs = [abs(query_dims[0] - stock_dims[0]), abs(query_dims[1] - stock_dims[1])]
    if max(diffs) < 0.001:
        return 1.0
    if max(diffs) <= 50:
        return 0.8
    if max(diffs) <= 100:
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


def _generic_number_similarity(
    query_value: float, stock_values: Iterable[float]
) -> float:
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


def _token_score(
    query_features: dict[str, Any], stock_features: dict[str, Any]
) -> float:
    score = 0.0
    query_tokens = [
        token
        for token in query_features["tokens"]
        if token not in query_features["numeric_tokens"] and token != "x"
    ]
    for token in query_tokens:
        if token in stock_features["tokens"]:
            score += 7.0
        elif token in stock_features["normalized_text"]:
            score += 4.0
    for phrase in query_features["phrases"]:
        if phrase and phrase in stock_features["normalized_text"]:
            score += 20.0
    return score


def _form_score(
    query_features: dict[str, Any], stock_features: dict[str, Any]
) -> float:
    query_forms = query_features["forms"]
    stock_forms = stock_features["forms"]
    if not query_forms:
        return 0.0
    if query_forms & stock_forms:
        return 28.0 * len(query_forms & stock_forms)
    if stock_forms:
        return -18.0
    return 0.0


def _measurement_score(
    query_features: dict[str, Any], stock_features: dict[str, Any]
) -> float:
    score = 0.0
    if query_features["dimension_pairs"]:
        best = 0.0
        for query_dims in query_features["dimension_pairs"]:
            for stock_dims in stock_features["dimension_pairs"]:
                best = max(best, _dimension_similarity(query_dims, stock_dims))
        score += best * 18.0
    if query_features["thicknesses"]:
        best = 0.0
        for query_thickness in query_features["thicknesses"]:
            for stock_thickness in stock_features["thicknesses"]:
                best = max(
                    best, _thickness_similarity(query_thickness, stock_thickness)
                )
        score += best * 16.0

    consumed_numbers: set[str] = set()
    for thickness in query_features["thicknesses"]:
        consumed_numbers.update(_normalize_number(thickness))
    for first, second in query_features["dimension_pairs"]:
        consumed_numbers.update(_normalize_number(first))
        consumed_numbers.update(_normalize_number(second))

    for raw in query_features["numeric_tokens"] - consumed_numbers:
        query_value = float(raw)
        if query_features["forms"] & {"round_bar", "flat_bar"} and query_value < 100:
            score += (
                _thickness_similarity(query_value, stock_features["thicknesses"][0])
                * 12.0
                if stock_features["thicknesses"]
                else 0.0
            )
        score += (
            _generic_number_similarity(query_value, stock_features["numeric_values"])
            * 10.0
        )
    return score


def _usage_score(stock: Stock, usage_counts: dict[str, int]) -> float:
    if not stock.item_code:
        return 0.0
    return math.log1p(usage_counts.get(stock.item_code, 0))


def _matches(query_features: dict[str, Any], stock_features: dict[str, Any]) -> bool:
    if query_features["phrases"]:
        return any(
            phrase in stock_features["normalized_text"]
            for phrase in query_features["phrases"]
        )
    return True


def _score_stock(
    stock: Stock,
    query_features: dict[str, Any],
    usage_counts: dict[str, int],
) -> float:
    stock_features = _build_features(_build_stock_text(stock))
    if not _matches(query_features, stock_features):
        return 0.0
    score = _token_score(query_features, stock_features)
    score += _form_score(query_features, stock_features)
    score += _measurement_score(query_features, stock_features)
    score += _usage_score(stock, usage_counts)
    return score


def _sorted_stock_matches(query: str) -> tuple[list[Stock], dict[str, int]]:
    query = _normalize_search_query(query)
    usage_counts = _usage_counts_by_item_code()
    query_features = _build_features(query)
    scored: list[tuple[float, Stock]] = []
    for stock in Stock.objects.filter(is_active=True):
        score = _score_stock(stock, query_features, usage_counts)
        if score > 0:
            scored.append((score, stock))
    scored.sort(
        key=lambda item: (
            -item[0],
            item[1].description.lower(),
            item[1].item_code or "",
        )
    )
    return [stock for _, stock in scored], usage_counts


def _serialize(
    stock_qs, usage_counts: dict[str, int] | None = None
) -> List[Dict[str, Any]]:
    usage_counts = usage_counts or {}
    stock_items = list(stock_qs)
    for stock in stock_items:
        stock.times_used = usage_counts.get(stock.item_code or "", 0)
    return StockItemSerializer(stock_items, many=True).data


def search_stock(query: str, limit: int = 10) -> List[Dict[str, Any]]:
    """
    Quick top-N search for typeahead/autocomplete callers.

    Returns [] for queries shorter than 3 characters; matches the guard
    used by ClientRestService.search_clients.
    """
    try:
        if not query or len(query.strip()) < 3:
            return []

        query = _normalize_search_query(query)
        limit = max(1, min(limit, 50))
        logger.info("Stock typeahead search query=%r limit=%s", query, limit)
        results, usage_counts = _sorted_stock_matches(query)
        results = results[:limit]
        logger.info(
            "Stock typeahead search completed query=%r results=%s",
            query,
            len(results),
        )
        return _serialize(results, usage_counts)

    except AlreadyLoggedException:
        raise
    except ValueError:
        raise
    except Exception as exc:
        persist_and_raise(exc, additional_context={"query": query, "limit": limit})


def list_stock(
    query: str | None = None,
    page: int = 1,
    page_size: int = 50,
    sort_by: str = "description",
    sort_dir: str = "asc",
) -> Dict[str, Any]:
    """
    Paginated stock listing with optional FTS filter.
    """
    try:
        sort_field = ALLOWED_SORT_FIELDS.get(sort_by, "description")
        if sort_dir.lower() == "desc":
            sort_field = f"-{sort_field}"

        queryset = Stock.objects.filter(is_active=True)

        if query:
            query = _normalize_search_query(query)
            logger.info(
                "Stock paginated search query=%r page=%s page_size=%s sort_by=%s sort_dir=%s",
                query,
                page,
                page_size,
                sort_by,
                sort_dir,
            )
            items, usage_counts = _sorted_stock_matches(query)
        else:
            ordering = (sort_field,)
            items = list(queryset.order_by(*ordering))
            usage_counts = _usage_counts_by_item_code()

        total_count = len(items)

        offset = (page - 1) * page_size
        items = items[offset : offset + page_size]

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

    except AlreadyLoggedException:
        raise
    except ValueError:
        raise
    except Exception as exc:
        persist_and_raise(
            exc,
            additional_context={
                "query": query,
                "page": page,
                "page_size": page_size,
            },
        )
