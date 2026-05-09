"""
Stock search service.

Postgres FTS over Stock with the same shape as ClientRestService.list_clients
and ClientRestService.search_clients. The search vector spans the user-facing
free-text fields plus the vetted structured fields (metal_type, alloy,
specifics) which often canonicalise synonyms in description, so a query for
"stainless" matches a row whose description used "S/S" but whose metal_type
was vetted to "stainless steel".
"""

from typing import Any, Dict, List

from django.contrib.postgres.search import SearchVector

from apps.purchasing.models import Stock
from apps.purchasing.serializers import StockItemSerializer
from apps.workflow.exceptions import AlreadyLoggedException
from apps.workflow.services.error_persistence import persist_and_raise
from apps.workflow.services.search import apply_text_search

# Weighted vector: identifying fields (description, item_code) rank highest;
# the structured-extract fields rank one tier below; location is a weak signal.
STOCK_SEARCH_VECTOR = (
    SearchVector("description", weight="A", config="english")
    + SearchVector("item_code", weight="A", config="english")
    + SearchVector("metal_type", weight="B", config="english")
    + SearchVector("alloy", weight="B", config="english")
    + SearchVector("specifics", weight="B", config="english")
    + SearchVector("location", weight="C", config="english")
)

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


def _serialize(stock_qs) -> List[Dict[str, Any]]:
    return StockItemSerializer(stock_qs, many=True).data


def search_stock(query: str, limit: int = 10) -> List[Dict[str, Any]]:
    """
    Quick top-N search for typeahead/autocomplete callers.

    Returns [] for queries shorter than 3 characters; matches the guard
    used by ClientRestService.search_clients.
    """
    try:
        if not query or len(query.strip()) < 3:
            return []

        query = query.strip()
        limit = max(1, min(limit, 50))

        base_qs = Stock.objects.filter(is_active=True)
        ranked = apply_text_search(base_qs, query, STOCK_SEARCH_VECTOR)
        results = ranked.order_by("-search_rank", "description")[:limit]
        return _serialize(results)

    except AlreadyLoggedException:
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
            queryset = apply_text_search(queryset, query, STOCK_SEARCH_VECTOR)
            ordering = ("-search_rank", sort_field)
        else:
            ordering = (sort_field,)

        total_count = queryset.count()

        offset = (page - 1) * page_size
        items = queryset.order_by(*ordering)[offset : offset + page_size]

        total_pages = (total_count + page_size - 1) // page_size

        return {
            "results": _serialize(items),
            "count": total_count,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
        }

    except AlreadyLoggedException:
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
