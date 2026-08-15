"""The progress channel between the payroll-posting task and its SSE stream.

The task writes events here; the stream endpoint reads them. Keeping the
transport in one module is what lets the stream stay a pure read — it never
needs to know that posting is happening, only that events arrive.

Events accumulate in a cache list rather than a pub/sub channel so a client
that connects late, or reconnects after a dropped connection, still receives
everything from the beginning. v1 lost the whole record when the connection
dropped, because the connection WAS the work.
"""

import logging
from typing import Any, TypedDict

from django.core.cache import cache

from apps.accounting.types import StaffWeekPostResult

logger = logging.getLogger(__name__)

# Long enough for an operator to reconnect after a dropped connection, short
# enough that a finished week's events do not outlive interest in them.
TASK_TIMEOUT_SECONDS = 3600
TASK_CACHE_PREFIX = "payroll_task_"
EVENTS_CACHE_SUFFIX = "_events"

TERMINAL_EVENTS = frozenset({"done", "error"})


class PayrollTaskData(TypedDict):
    """What the POST recorded about a posting run, for the stream to validate against."""

    staff_ids: list[str]
    week_start_date: str
    status: str


def task_key(task_id: str) -> str:
    """Build the cache key holding a posting run's registration."""
    return f"{TASK_CACHE_PREFIX}{task_id}"


def events_key(task_id: str) -> str:
    """Build the cache key holding a posting run's published events."""
    return f"{TASK_CACHE_PREFIX}{task_id}{EVENTS_CACHE_SUFFIX}"


def register(task_id: str, staff_ids: list[str], week_start_date: str) -> None:
    """Record a posting run so its stream can be opened before the task starts."""
    data: PayrollTaskData = {
        "staff_ids": staff_ids,
        "week_start_date": week_start_date,
        "status": "pending",
    }
    cache.set(task_key(task_id), data, timeout=TASK_TIMEOUT_SECONDS)
    cache.set(events_key(task_id), [], timeout=TASK_TIMEOUT_SECONDS)


def get_task(task_id: str) -> PayrollTaskData | None:
    """Read the registration for a posting run; None once it has expired."""
    task: PayrollTaskData | None = cache.get(task_key(task_id))
    return task


def publish(task_id: str, event: dict[str, Any]) -> None:
    """Append an event to the run's log for the stream to pick up.

    Read-modify-write on a cache list is not atomic, but the only writer is the
    single task that owns this id — concurrency here would mean two tasks for
    one run, which the caller's fresh uuid rules out.
    """
    events: list[dict[str, Any]] = cache.get(events_key(task_id)) or []
    events.append(event)
    cache.set(events_key(task_id), events, timeout=TASK_TIMEOUT_SECONDS)


def events_since(task_id: str, offset: int) -> list[dict[str, Any]]:
    """Every event published after ``offset``, so a reader can resume."""
    events: list[dict[str, Any]] = cache.get(events_key(task_id)) or []
    return events[offset:]


def is_terminal(event: dict[str, Any]) -> bool:
    """Whether this event ends the run, so the stream can close."""
    return event.get("event") in TERMINAL_EVENTS


def completion_event(result: StaffWeekPostResult) -> dict[str, Any]:
    """Shape one staff member's outcome as a wire event.

    Hours are strings: they are Decimals, and JSON floats would round money-
    adjacent figures the operator is reconciling against Xero (ADR 0046 puts
    numbers on the wire, but not at the cost of precision here).
    """
    return {
        "event": "complete",
        "staff_id": result.staff_id,
        "staff_name": result.staff_name,
        "success": result.success,
        "timesheet_id": result.timesheet_id,
        "entries_posted": result.entries_posted,
        "work_hours": str(result.work_hours),
        "other_leave_hours": str(result.other_leave_hours),
        "leave_hours": str(result.leave_hours),
        "skipped": result.skipped,
        "reason": result.reason,
        "has_entries": result.has_entries,
        "error": result.error,
    }
