"""
Postgres full-text search helpers shared across apps.

Centralises `SearchQuery` + `SearchRank` annotation so callers only supply
the queryset and a pre-built `SearchVector`. The `config` and `search_type`
parameters are seams for future synonym dictionaries and fuzzy fallbacks
(see Trello #312).
"""

from typing import Any

from django.contrib.postgres.search import SearchQuery, SearchRank


def apply_text_search(
    qs: Any,
    query: str,
    vector: Any,
    *,
    config: str = "english",
    search_type: str = "websearch",
) -> Any:
    """
    Annotate `qs` with `search_rank` from `SearchRank(vector, query)` and
    drop rows that don't match.

    The match filter is the Postgres `@@` operator (expressed in Django as
    ``qs.annotate(search_doc=vector).filter(search_doc=sq)``). We can't use
    ``search_rank__gt=0`` to filter — `ts_rank` returns a tiny non-zero
    epsilon (~1e-20) for documents that don't match the query at all, so
    that filter would return every row in the table.

    Callers combine the helper's output with their own `order_by`,
    typically `order_by("-search_rank", existing_sort_field)` so the FTS
    score dominates and the previous default sort acts as a tie-breaker.
    """
    sq = SearchQuery(query, search_type=search_type, config=config)
    return qs.annotate(search_doc=vector, search_rank=SearchRank(vector, sq)).filter(
        search_doc=sq
    )
