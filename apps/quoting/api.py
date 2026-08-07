"""The quoting domain's ninja router (thin translators over the services).

Paths and operationIds match v1's generated OpenAPI schema
(v1's published schema), served from v1's ``apps/quoting/urls.py``:

- ``/api/quoting/scheduled-tasks/`` and ``/{id}/``            — the beat schedule
- ``/api/quoting/scheduled-task-executions/`` and ``/{id}/``  — its history

Those four operations are the whole of ``/api/quoting/`` in the schema. v1's
router also mounted a fifth path, ``POST /api/quoting/extract-supplier-price-list/``,
which is deliberately not ported — it is a plain function view that
drf-spectacular never emitted, it appears nowhere in v1's published schema, and
no v1 frontend module calls it. The reasoning and the pick-up instructions live
in ``apps/quoting/services/price_extraction.py``.

Auth per v1: both viewsets carried ``IsAuthenticated + IsOfficeStaff``, so both
use ``OfficeStaffCookieJWTAuth`` — this is an admin screen. That is stricter
than the purchasing router, which v1 left open to any authenticated staff.

Pagination is v1's ``FiftyPerPagePagination``: fifty rows a page, DRF's
``count``/``next``/``previous``/``results`` envelope, ``?page=`` and ``?search=``.

Integration wiring (``config/api.py``): ``api.add_router("/", router)`` — the
paths below carry their own ``/quoting/`` prefix.
"""

import logging
from typing import TYPE_CHECKING

from django.core.paginator import InvalidPage, Paginator
from django.http import Http404, HttpRequest
from django_celery_results.models import TaskResult
from ninja import Router

from apps.core.auth import OfficeStaffCookieJWTAuth
from apps.quoting.schemas import (
    PaginatedScheduledTaskExecutionList,
    PaginatedScheduledTaskList,
    ScheduledTask,
    ScheduledTaskExecution,
)
from apps.quoting.services import scheduled_task_service

if TYPE_CHECKING:
    # django-stubs marks the paginator's input protocol type-check-only.
    from django.core.paginator import _SupportsPagination

logger = logging.getLogger(__name__)

router = Router()

auth = OfficeStaffCookieJWTAuth()

# v1 FiftyPerPagePagination.page_size; no page_size query param (that was the
# other v1 paginator).
PAGE_SIZE = 50


def _page_link(request: HttpRequest, page: int) -> str:
    """Absolute URI for another page of this listing, as DRF emitted."""
    query = request.GET.copy()
    query["page"] = str(page)
    return request.build_absolute_uri(f"{request.path}?{query.urlencode()}")


def _paginate[Row](
    request: HttpRequest, rows: "_SupportsPagination[Row]", page: int
) -> dict[str, object]:
    """Wrap a row list or queryset in v1's PageNumberPagination envelope.

    Takes the paginator's own input protocol so a queryset is sliced in the
    database (the executions listing) while a plain list still works (the beat
    schedule, which lives in memory).
    """
    paginator = Paginator(rows, PAGE_SIZE)
    try:
        page_obj = paginator.page(page)
    except InvalidPage as exc:
        raise Http404(f"Invalid page ({page}): {exc}") from exc
    return {
        "count": paginator.count,
        "next": _page_link(request, page_obj.next_page_number()) if page_obj.has_next() else None,
        "previous": _page_link(request, page_obj.previous_page_number())
        if page_obj.has_previous()
        else None,
        "results": list(page_obj.object_list),
    }


@router.get(
    "/quoting/scheduled-tasks/",
    auth=auth,
    operation_id="quoting_scheduled_tasks_list",
    response=PaginatedScheduledTaskList,
    summary="List the Celery Beat schedule",
    tags=["quoting"],
)
def quoting_scheduled_tasks_list(
    request: HttpRequest, page: int = 1, search: str | None = None
) -> dict[str, object]:
    """List beat-schedule entries by name, with their last recorded run."""
    return _paginate(request, scheduled_task_service.list_scheduled_tasks(search), page)


@router.get(
    "/quoting/scheduled-tasks/{int:task_id}/",
    auth=auth,
    operation_id="quoting_scheduled_tasks_retrieve",
    response=ScheduledTask,
    summary="Retrieve one Celery Beat schedule entry",
    tags=["quoting"],
)
def quoting_scheduled_tasks_retrieve(
    request: HttpRequest, task_id: int
) -> scheduled_task_service.ScheduledTaskData:
    """Retrieve a single schedule entry by its listing position."""
    task = scheduled_task_service.get_scheduled_task(task_id)
    if task is None:
        raise Http404(f"No scheduled task with id {task_id}")
    return task


@router.get(
    "/quoting/scheduled-task-executions/",
    auth=auth,
    operation_id="quoting_scheduled_task_executions_list",
    response=PaginatedScheduledTaskExecutionList,
    summary="List beat-fired task executions",
    tags=["quoting"],
)
def quoting_scheduled_task_executions_list(
    request: HttpRequest, page: int = 1, search: str | None = None
) -> dict[str, object]:
    """List task executions that a beat schedule fired, newest first."""
    return _paginate(request, scheduled_task_service.beat_fired_executions(search), page)


@router.get(
    "/quoting/scheduled-task-executions/{int:execution_id}/",
    auth=auth,
    operation_id="quoting_scheduled_task_executions_retrieve",
    response=ScheduledTaskExecution,
    summary="Retrieve one beat-fired task execution",
    tags=["quoting"],
)
def quoting_scheduled_task_executions_retrieve(
    request: HttpRequest, execution_id: int
) -> TaskResult:
    """Retrieve one beat-fired execution by its TaskResult id."""
    execution = scheduled_task_service.beat_fired_executions().filter(id=execution_id).first()
    if execution is None:
        raise Http404(f"No beat-fired task execution with id {execution_id}")
    return execution
