"""Pydantic wire contracts for the quoting router.

Scheduled-task endpoints use the ``count``/``next``/``previous``/``results``
pagination envelope. Company and CRM listings intentionally use a different
page-number envelope, so the two shapes must not be conflated (ADR 0039).
"""

from datetime import datetime

from ninja import Schema


class ScheduledTask(Schema):
    """One task from the in-code Celery beat schedule.

    See ``apps/quoting/services/scheduled_task_service.py`` for how ``id``,
    ``enabled`` and ``last_run_at`` are derived without database schedule rows.
    """

    id: int
    name: str
    task: str
    enabled: bool
    last_run_at: datetime | None
    schedule: str


class PaginatedScheduledTaskList(Schema):
    """Cursor-style pagination envelope over scheduled tasks."""

    count: int
    next: str | None = None
    previous: str | None = None
    results: list[ScheduledTask]


class ScheduledTaskExecution(Schema):
    """Public execution fields derived from a Celery ``TaskResult``.

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
    """Cursor-style pagination envelope over task executions."""

    count: int
    next: str | None = None
    previous: str | None = None
    results: list[ScheduledTaskExecution]
