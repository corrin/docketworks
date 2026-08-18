"""The record of a payroll-posting run: who owns it, and what it has reported.

The task writes events here; the stream endpoint reads them. Keeping the
transport in one module is what lets the stream stay a pure read — it never
needs to know that posting is happening, only that events arrive.

The run CLAIM lives here too rather than in a module of its own, because it is
the same fact from the other side — which run is live — and it needs the same
cross-process cache for the same reason.

Events accumulate in a cache list rather than a pub/sub channel so a client
that connects late, or reconnects after a dropped connection, still receives
everything from the beginning. v1 lost the whole record when the connection
dropped, because the connection WAS the work.

**The "shared" cache, never the default one.** The writer is the Celery worker
and the reader is the web process, so a per-process cache is not a channel at
all — it is two caches that never meet. The default backend is LocMemCache,
and with it the post ran to completion against Xero while the page waited on a
stream that could never emit anything: payroll written, no results shown, and
an operator whose only evidence is a spinner. Settings keeps "shared" on Redis
for exactly this pairing.
"""
# Opus: docstring rationale unratified (ADR 0051).

import logging
from typing import Any, TypedDict

from django.core.cache import BaseCache, caches

from apps.accounting.types import StaffWeekPostResult

logger = logging.getLogger(__name__)


# Opus: docstring rationale unratified (ADR 0051).
def _cache() -> BaseCache:
    """Return the cross-process cache the worker and the web process both reach.

    Resolved per call, not bound at import. Django hands out a cache instance
    per thread and discards it on teardown, so a module-level binding can
    outlive the instance it captured — and under a threaded server the object a
    module holds is not necessarily the one the handler is currently giving
    everyone else.
    """
    return caches["shared"]


# Opus: Long enough for an operator to reconnect after a dropped connection, short
# enough that a finished week's events do not outlive interest in them.
TASK_TIMEOUT_SECONDS = 3600
TASK_CACHE_PREFIX = "payroll_task_"
EVENTS_CACHE_SUFFIX = "_events"

TERMINAL_EVENTS = frozenset({"done", "error"})


class PayrollTaskData(TypedDict):
    """What the POST recorded about a posting run, for the stream to validate against."""

    staff_ids: list[str]
    week_start_date: str


def task_key(task_id: str) -> str:
    """Build the cache key holding a posting run's registration."""
    return f"{TASK_CACHE_PREFIX}{task_id}"


def events_key(task_id: str) -> str:
    """Build the cache key holding a posting run's published events."""
    return f"{TASK_CACHE_PREFIX}{task_id}{EVENTS_CACHE_SUFFIX}"


def register(task_id: str, staff_ids: list[str], week_start_date: str) -> None:
    """Record a posting run so its stream can be opened before the task starts."""
    # A "status" field lived here and was never read. It looked like the dedup
    # key ADR 0024 asks for and could not be one: read-then-write is not atomic,
    # so two deliveries both see "pending" and both proceed. The claim below is
    # the mechanism that actually excludes them.
    data: PayrollTaskData = {
        "staff_ids": staff_ids,
        "week_start_date": week_start_date,
    }
    _cache().set(task_key(task_id), data, timeout=TASK_TIMEOUT_SECONDS)
    _cache().set(events_key(task_id), [], timeout=TASK_TIMEOUT_SECONDS)


def get_task(task_id: str) -> PayrollTaskData | None:
    """Read the registration for a posting run; None once it has expired."""
    task: PayrollTaskData | None = _cache().get(task_key(task_id))
    return task


# Opus: docstring rationale unratified (ADR 0051).
def publish(task_id: str, event: dict[str, Any]) -> None:
    """Append an event to the run's log for the stream to pick up.

    Read-modify-write on a cache list is not atomic, but the only writer is the
    single task that owns this id — concurrency here would mean two tasks for
    one run, which the caller's fresh uuid rules out.
    """
    events: list[dict[str, Any]] = _cache().get(events_key(task_id)) or []
    events.append(event)
    _cache().set(events_key(task_id), events, timeout=TASK_TIMEOUT_SECONDS)


def events_since(task_id: str, offset: int) -> list[dict[str, Any]]:
    """Every event published after ``offset``, so a reader can resume."""
    events: list[dict[str, Any]] = _cache().get(events_key(task_id)) or []
    return events[offset:]


def is_terminal(event: dict[str, Any]) -> bool:
    """Whether this event ends the run, so the stream can close."""
    return event.get("event") in TERMINAL_EVENTS


# Opus: docstring rationale unratified (ADR 0051).
def completion_event(result: StaffWeekPostResult) -> dict[str, Any]:
    """Shape one staff member's outcome as a wire event.

    Hours are JSON numbers, like every other quantity this API sends (ADR
    0046). They were strings, on the reasoning that a float would round figures
    an operator reconciles against Xero — but the rounding that mattered was in
    the ACCUMULATION, which is Decimal from the pay item to here, and a string
    quantity costs every consumer a parse it can forget. These totals carry
    three decimal places at hour magnitudes; a JSON number holds them exactly.
    """
    return {
        "event": "complete",
        "staff_id": result.staff_id,
        "staff_name": result.staff_name,
        "success": result.success,
        "timesheet_id": result.timesheet_id,
        "entries_posted": result.entries_posted,
        "work_hours": float(result.work_hours),
        "other_leave_hours": float(result.other_leave_hours),
        "leave_hours": float(result.leave_hours),
        "skipped": result.skipped,
        "reason": result.reason,
        "has_entries": result.has_entries,
        "error": result.error,
        "posting_mode": result.posting_mode,
        "salary_timesheet_removed": result.salary_timesheet_removed,
    }


# ---------------------------------------------------------------------------
# The run claim: one live posting run per connected organisation
# ---------------------------------------------------------------------------

CLAIM_CACHE_PREFIX = "payroll_claim_"

#: How long a claim survives without renewal.
#:
#: Sized to exceed the longest gap between renewals, not the length of a run.
#: The longest gap is the leave-reconcile preflight, which runs before the first
#: staff result is yielded and costs one ``get_employee_leaves`` call per staff
#: member — about four seconds each at the payroll pacing interval, so roughly
#: 160s for forty staff. Ten minutes clears any plausible staff list with room
#: to spare, so a LIVE run never loses its claim.
#:
#: It is also the liveness bound: a worker killed hard cannot release its claim,
#: and payroll is then blocked until this expires. Ten minutes is the price of
#: the alternative being two runs deleting each other's timesheet lines.
#:
#: Rejected alternative: a shorter TTL with stale-owner takeover decided from the
#: last published event. It buys a faster recovery for a failure mode that needs
#: a hard kill to reach, and pays for it with a takeover race that has to be got
#: right on the one path where being wrong means posting payroll twice.
CLAIM_TTL_SECONDS = 600


class PayrollRunClaimLostError(RuntimeError):
    """Another posting run holds this payroll calendar, or took it over."""


def claim_key(connection_id: str) -> str:
    """Build the cache key naming the live posting run for one organisation."""
    return f"{CLAIM_CACHE_PREFIX}{connection_id}"


def acquire_run_claim(connection_id: str, task_id: str) -> str | None:
    """Claim the organisation for this run, or name the run that already holds it.

    ``cache.add`` is set-if-absent — on Redis a single ``SET NX EX`` — so two
    deliveries of the same task, two browser tabs, and two operators all resolve
    here rather than in a read-then-write that both sides win. The same
    primitive guards the data-versions publish lock (``apps/operations/push.py``).

    Keyed on the CONNECTION, not the task: a second click produces a second task
    id, which is the likelier collision and which a task-scoped guard would miss
    entirely. What Xero serialises is the payroll calendar — one Draft pay run
    each — and this installation has exactly one
    (``CompanyDefaults.xero_payroll_calendar_id`` is a single field), so the
    connection is that same lock without a second lookup that could disagree
    with the one the write itself resolves.

    Returns ``None`` on success and the holding task id otherwise — the caller
    reports which run is live, so an operator is not left guessing.
    """
    key = claim_key(connection_id)
    if _cache().add(key, task_id, timeout=CLAIM_TTL_SECONDS):
        return None
    holder: str | None = _cache().get(key)
    # Expired between the add and the read: the next delivery gets it. Reporting
    # the run as held is still the right answer for this one, because it did not
    # acquire the claim and must not post.
    return holder if holder is not None else "an expired run"


def renew_run_claim(connection_id: str, task_id: str) -> None:
    """Extend this run's claim, refusing to continue if it is no longer ours.

    Losing the claim mid-run means it expired and another run may now be writing
    to the same organisation, which is the corruption the claim exists to
    prevent — so this raises rather than logging. With the TTL above, that
    cannot happen to a run that is still making progress.
    """
    key = claim_key(connection_id)
    if _cache().get(key) != task_id:
        raise PayrollRunClaimLostError(
            f"Payroll run {task_id} no longer holds the posting claim for Xero "
            f"organisation {connection_id}. Another run may be posting it; stopping "
            "here rather than writing over it."
        )
    _cache().touch(key, timeout=CLAIM_TTL_SECONDS)


def release_run_claim(connection_id: str, task_id: str) -> None:
    """Release the claim, but only if this run still owns it."""
    key = claim_key(connection_id)
    if _cache().get(key) == task_id:
        _cache().delete(key)
