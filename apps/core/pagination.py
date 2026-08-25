"""The one pagination envelope (v1 PageSizePagination wire contract)."""

from dataclasses import dataclass

from django.core.paginator import InvalidPage, Paginator
from django.db.models import Model, QuerySet
from django.http import Http404

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 100


@dataclass(frozen=True, slots=True)
class PageData[M: Model]:
    """One page of rows plus the v1 pagination envelope numbers."""

    rows: list[M]
    count: int
    page: int
    page_size: int
    total_pages: int


def paginate[M: Model](queryset: QuerySet[M], *, page: int, page_size: int | None) -> PageData[M]:
    """Slice ``queryset`` DRF-style; raise Http404 for an out-of-range page.

    Envelope: ``{"results", "count", "page", "page_size", "total_pages"}``
    with a default page size of 50 and a ``page_size`` query param capped at
    100 (v1 ``PageSizePagination``). Lives in core because company, CRM and
    process all page lists.
    """
    if page_size is None or page_size <= 0:
        effective_size = DEFAULT_PAGE_SIZE
    else:
        effective_size = min(page_size, MAX_PAGE_SIZE)
    paginator = Paginator(queryset, effective_size)
    try:
        page_obj = paginator.page(page)
    except InvalidPage as exc:
        raise Http404(f"Invalid page ({page}): {exc}") from exc
    return PageData(
        rows=list(page_obj.object_list),
        count=paginator.count,
        page=page_obj.number,
        page_size=effective_size,
        total_pages=paginator.num_pages,
    )
