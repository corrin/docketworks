"""The Celery Beat schedule and its execution history, for the admin screen.

The surface is read-only; create, update, delete, and run-now controls are not
part of this application. Beat schedules are declared in ``config/celery.py``
so they are code-reviewed and environment-diffable. This module reads the live
schedule through ``celery.current_app`` rather than importing ``config``, which
sits above domain apps in the layer contract.

What that costs, field by field:

- ``id`` — assigns the 1-based position in the name-sorted schedule. It is stable
  for a given deployment, which is all the two consumers need: the frontend uses
  it as a list key, and the retrieve endpoint addresses a row by it.
- ``enabled`` — an in-code schedule has no mutable toggle, so every entry that
  exists is enabled. Disabling one means deleting
  or commenting it out in ``config/celery.py``, which is the point of moving
  schedules into code.
- ``last_run_at`` — is derived from the newest ``TaskResult`` recorded for the
  entry. Same question, same
  answer, one fewer piece of mutable state.

BEAT WIRING: this module finds executions by ``TaskResult.periodic_task_name``,
which ``django_celery_results`` fills from a message header that
``django_celery_beat`` would set and a plain in-code schedule would not. That
header is stamped onto every entry by ``_with_periodic_task_headers`` in
``config/celery.py``; without it every execution is recorded with a NULL name
and this module reports every task as never having run.
``config/tests/test_celery_beat.py`` holds the invariant.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from celery import current_app
from celery.schedules import BaseSchedule, maybe_schedule
from django.db.models import Q, QuerySet
from django_celery_results.models import TaskResult

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ScheduledTaskData:
    """One beat-schedule entry."""

    id: int
    name: str
    task: str
    enabled: bool
    last_run_at: datetime | None
    schedule: str


def render_schedule(schedule: timedelta | BaseSchedule) -> str:
    """Render a beat schedule as the human string the UI prints.

    v1 rendered ``str(CrontabSchedule)``/``str(IntervalSchedule)`` so the UI
    never has to know which shape it got. Celery's own schedule objects
    stringify to ``<crontab: 0 2 * * * (m/h/dM/MY/d)>`` and ``<freq: 5.00
    minutes>``; the decoration is stripped so the payload reads the same way
    v1's did. Bare numbers and timedeltas are accepted because celery's beat
    accepts them as shorthand for an interval.
    """
    text = str(maybe_schedule(schedule))
    if text.startswith("<") and text.endswith(">"):
        text = text[1:-1]
    return text.removeprefix("crontab: ").removeprefix("freq: ")


def _beat_entries() -> list[tuple[str, str, str]]:
    """Return (name, task, schedule string) for every entry, sorted by name.

    v1 ordered the PeriodicTask queryset by name; sorting here keeps both the
    listing order and the assigned ids stable.
    """
    schedule = current_app.conf.beat_schedule or {}
    entries: list[tuple[str, str, str]] = []
    for name in sorted(schedule):
        entry = schedule[name]
        task = entry.get("task")
        if not isinstance(task, str):
            raise TypeError(
                f"Beat schedule entry {name!r} has no 'task' name; "
                f"config/celery.py must give every entry a dotted task path."
            )
        raw_schedule = entry.get("schedule")
        if isinstance(raw_schedule, int | float):
            # Celery's shorthand for "every N seconds".
            raw_schedule = timedelta(seconds=raw_schedule)
        if not isinstance(raw_schedule, timedelta | BaseSchedule):
            raise TypeError(
                f"Beat schedule entry {name!r} has schedule of type "
                f"{type(raw_schedule).__name__}; celery accepts a crontab, a "
                f"timedelta, or a number of seconds."
            )
        entries.append((name, task, render_schedule(raw_schedule)))
    return entries


def _last_run_times(names: list[str]) -> dict[str, datetime]:
    """Newest recorded completion per beat entry name, in one query."""
    if not names:
        return {}
    rows = (
        TaskResult.objects.filter(periodic_task_name__in=names)
        .order_by("periodic_task_name", "-date_done")
        .values_list("periodic_task_name", "date_done")
    )
    latest: dict[str, datetime] = {}
    for periodic_task_name, date_done in rows:
        if periodic_task_name is not None and periodic_task_name not in latest:
            latest[periodic_task_name] = date_done
    return latest


def list_scheduled_tasks(search: str | None = None) -> list[ScheduledTaskData]:
    """List beat-schedule entries, optionally filtered by v1's search fields.

    v1's ``search_fields = ["name", "task"]`` was DRF's SearchFilter:
    case-insensitive substring, matching if any field hits.
    """
    entries = _beat_entries()
    last_run = _last_run_times([name for name, _task, _schedule in entries])

    needle = (search or "").strip().lower()
    tasks: list[ScheduledTaskData] = []
    for position, (name, task, schedule) in enumerate(entries, start=1):
        if needle and needle not in name.lower() and needle not in task.lower():
            continue
        tasks.append(
            ScheduledTaskData(
                id=position,
                name=name,
                task=task,
                enabled=True,
                last_run_at=last_run.get(name),
                schedule=schedule,
            )
        )
    return tasks


def get_scheduled_task(task_id: int) -> ScheduledTaskData | None:
    """Return one entry by its assigned position, or None."""
    for task in list_scheduled_tasks():
        if task.id == task_id:
            return task
    return None


def beat_fired_executions(search: str | None = None) -> QuerySet[TaskResult]:
    """Beat-fired task executions, newest first, optionally searched.

    v1 excluded ``TaskResult`` rows with an empty ``periodic_task_name`` —
    those are ad-hoc Celery work (webhook handlers, health checks) that would
    otherwise drown out the scheduled-task history this screen exists for. The
    search reproduces DRF's ``search_fields = ["task_name",
    "periodic_task_name", "status"]``: case-insensitive substring, any field.
    """
    rows = (
        TaskResult.objects.exclude(periodic_task_name__isnull=True)
        .exclude(periodic_task_name="")
        .order_by("-date_done")
    )
    needle = (search or "").strip()
    if not needle:
        return rows
    return rows.filter(
        Q(task_name__icontains=needle)
        | Q(periodic_task_name__icontains=needle)
        | Q(status__icontains=needle)
    )
