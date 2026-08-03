"""Pydantic schemas for the quoting router (wire shapes match frontend/schema.yml).

The pagination envelope is DRF's ``PageNumberPagination`` — ``count`` / ``next``
/ ``previous`` / ``results`` — because v1 served these two viewsets through
``FiftyPerPagePagination``. That is a different envelope from the
``results``/``count``/``page``/``page_size``/``total_pages`` one used by the
company and CRM listings, which came from v1's ``PageSizePagination``; both v1
paginators are on the wire, so both survive here (see
``apps/job/schemas.py::JobDeltaRejectionListResponse`` for the other user of
this shape).
"""

from datetime import datetime

from ninja import Schema


class ScheduledTask(Schema):
    """v1 ScheduledTaskSerializer over django-celery-beat's PeriodicTask.

    v2 reads the in-code beat schedule instead; see
    ``apps/quoting/services/scheduled_task_service.py`` for what ``id``,
    ``enabled`` and ``last_run_at`` mean without those rows.
    """

    id: int
    name: str
    task: str
    enabled: bool
    last_run_at: datetime | None
    schedule: str


class PaginatedScheduledTaskList(Schema):
    """v1 FiftyPerPagePagination envelope over scheduled tasks."""

    count: int
    next: str | None = None
    previous: str | None = None
    results: list[ScheduledTask]


class ScheduledTaskExecution(Schema):
    """v1 ScheduledTaskExecutionSerializer over django-celery-results' TaskResult.

    ``task_name`` is the dotted Celery task; ``periodic_task_name`` is the beat
    entry's human name, and is what marks a row as beat-fired.
    """

    id: int
    task_id: str
    task_name: str | None
    periodic_task_name: str | None
    status: str
    date_created: datetime
    date_started: datetime | None
    date_done: datetime
    result: str | None
    traceback: str | None
    worker: str | None
    task_args: str | None
    task_kwargs: str | None


class PaginatedScheduledTaskExecutionList(Schema):
    """v1 FiftyPerPagePagination envelope over task executions."""

    count: int
    next: str | None = None
    previous: str | None = None
    results: list[ScheduledTaskExecution]
