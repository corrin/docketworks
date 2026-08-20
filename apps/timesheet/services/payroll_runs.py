"""The record of a payroll-posting run: who owns it, and what it has reported.

Opus: The task writes the run's current state here and this module pushes it;
the stream endpoint only subscribes. Keeping the transport in one module is what
lets the stream stay a pure read — it never needs to know that posting is
happening, only that documents arrive.

Opus: The run CLAIM lives here too rather than in a module of its own, because it is
the same fact from the other side — which run is live — and it needs the same
cross-process cache for the same reason.

The state is ONE document, rewritten in place, rather than a log of events
replayed from an offset. Every push carries the whole of it, so a client that
connects late, reconnects, or reloads needs the present rather than the history
(ADR 0047). v1 lost the whole record when the connection dropped, because the
connection WAS the work; the log that replaced it made replay exact and then
disagreed with the client about which event ended a run.

**The "shared" cache, never the default one.** The writer is the Celery worker
and the reader is the web process, so a per-process cache is not a channel at
all — it is two caches that never meet. The default backend is LocMemCache,
and with it the post ran to completion against Xero while the page waited on a
stream that could never emit anything: payroll written, no results shown, and
an operator whose only evidence is a spinner. Settings keeps "shared" on Redis
for exactly this pairing.
"""

import logging
from datetime import date
from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.conf import settings
from django.core.cache import BaseCache, caches
from django.utils import timezone

from apps.accounting.types import StaffWeekPostResult

if TYPE_CHECKING:
    from apps.timesheet.schemas import PayrollPostRunOut, PayrollRunsOut

logger = logging.getLogger(__name__)

#: Opus: The one event this channel carries, and its payload is exactly the
#: document the polling sibling serves — so a consumer needs no second shape.
PAYROLL_RUNS_EVENT = "payroll_runs"


def _cache() -> BaseCache:
    """Return the cross-process cache the worker and the web process both reach.

    Opus: Resolved per call, not bound at import. Django hands out a cache instance
    per thread and discards it on teardown, so a module-level binding can
    outlive the instance it captured — and under a threaded server the object a
    module holds is not necessarily the one the handler is currently giving
    everyone else.
    """
    return caches["shared"]


# Opus: Long enough for an operator to reconnect after a dropped connection, short
# enough that a finished week's document does not outlive interest in it.
RUN_TIMEOUT_SECONDS = 3600
RUN_CACHE_PREFIX = "payroll_run_post_"


def run_key(connection_id: str) -> str:
    """Build the cache key holding the posting run for one organisation.

    Opus: Keyed by CONNECTION, not by run id, for the same reason the claim beside
    it is: there is one payroll calendar, so there is one posting run, and a
    fixed key is what lets a reloaded page find its run again. Discovering a run
    by id required the page to still be holding the id it was given, so F5 lost
    the run permanently while its record sat in the cache for an hour.
    """
    return f"{RUN_CACHE_PREFIX}{connection_id}"


def write(connection_id: str, run: "PayrollPostRunOut") -> None:
    """Store the run's current state and push it to every connected tab.

    Opus: Storing and publishing are one call because they are one fact. Splitting
    them is how a document reaches the cache and never the stream, which is the
    shape of the bug that made a whole posting run invisible: the worker wrote to
    a per-process cache the web process could not read.

    Opus: The serialisation lives HERE, once. `model_dump(mode="json")` and not
    the pydantic object, because a mid-run deploy would otherwise unpickle a
    stale class; and not `mode="python"`, because `send_event` encodes with
    DjangoJSONEncoder, which renders Decimal as a STRING — straight into the
    review smell ADR 0046 names.
    """
    _cache().set(run_key(connection_id), run.model_dump(mode="json"), timeout=RUN_TIMEOUT_SECONDS)
    _publish(connection_id)


def _as_runs(stored: dict[str, Any] | None) -> "PayrollRunsOut":
    """Rebuild the typed document from what the cache holds.

    Opus: Validated on the way out rather than trusted. The cache is the one place
    a document can outlive the code that wrote it — a deploy mid-run leaves the
    previous release's shape under the same key — and validating turns that into
    a loud failure here instead of a missing field at the consumer. It is also
    what keeps ``dict[str, Any]`` from leaking past this module: everything above
    it holds the schema (ADR 0028).
    """
    # Call-time import: schemas import apps.accounting.types, which imports this
    # app's models through the registry.
    from apps.timesheet.schemas import PayrollPostRunOut, PayrollRunsOut  # noqa: PLC0415

    return PayrollRunsOut(post=None if stored is None else PayrollPostRunOut(**stored))


def read_runs(connection_id: str) -> "PayrollRunsOut":
    """Every run this organisation has state for."""
    return _as_runs(_cache().get(run_key(connection_id)))


def running(
    connection_id: str, run_id: str, week_start_date: "date", *, total: int
) -> "PayrollPostRunOut":
    """Open a run's document and store it before any Xero call is made.

    Opus: Written by the REQUEST handler so the panel can render "0 of N"
    immediately and a reload during the broker's queueing delay still finds a
    run. The shape this replaces registered a task id and an empty event
    list, which told a reader a run existed but nothing about it.

    Fable: The task calls this once more as its opening heartbeat — but only
    AFTER renewing its claim. The document is keyed by connection, so a caller
    that has not proven the claim would overwrite whichever run is live.
    """
    # Call-time import: schemas import apps.accounting.types, which imports this
    # app's models through the registry.
    from apps.timesheet.schemas import PayrollPostRunOut  # noqa: PLC0415

    run = PayrollPostRunOut(
        run_id=UUID(run_id),
        week_start_date=week_start_date,
        status="running",
        total=total,
        completed=0,
        successful=0,
        failed=0,
        current_staff_name=None,
        message=None,
        results=[],
        updated_at=timezone.now(),
    )
    write(connection_id, run)
    return run


def with_result(
    run: "PayrollPostRunOut",
    result: StaffWeekPostResult,
    *,
    completed: int,
    successful: int,
    failed: int,
) -> "PayrollPostRunOut":
    """Fold one staff member's outcome into the run.

    Opus: `model_validate` off the frozen dataclass rather than a hand-written
    flattening step — that step was a second declaration of these fourteen
    fields, and a third of them lived in TypeScript.
    """
    from apps.timesheet.schemas import StaffWeekPostResultOut  # noqa: PLC0415

    return run.model_copy(
        update={
            "results": [*run.results, StaffWeekPostResultOut.model_validate(result)],
            "completed": completed,
            "successful": successful,
            "failed": failed,
            "current_staff_name": result.staff_name,
            "updated_at": timezone.now(),
        }
    )


def finished(
    run: "PayrollPostRunOut", status: str, *, message: str | None = None
) -> "PayrollPostRunOut":
    """Close a run, carrying any batch-level message verbatim (ADR 0038)."""
    return run.model_copy(
        update={"status": status, "message": message, "updated_at": timezone.now()}
    )


def _publish(connection_id: str) -> None:
    """Push the whole current document to connected tabs.

    Opus: The complete document, not a delta, so a consumer needs no second parser
    and no replay — ADR 0047's latest-state-wins contract, which data-versions
    already proves. A dropped publication costs nothing: the next one carries
    everything, and the polling sibling closes any gap.
    """
    # Call-time import: django_eventstream reads Django settings at import.
    from django_eventstream import send_event  # noqa: PLC0415

    send_event(
        settings.PAYROLL_RUNS_CHANNEL,
        PAYROLL_RUNS_EVENT,
        read_runs(connection_id).model_dump(mode="json"),
    )


# ---------------------------------------------------------------------------
# The run claim: one live posting run per connected organisation
# ---------------------------------------------------------------------------

CLAIM_CACHE_PREFIX = "payroll_claim_"

#: Opus: How long a claim survives without renewal.
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

    Opus: ``cache.add`` is set-if-absent — on Redis a single ``SET NX EX`` — so two
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
    # Opus: Expired between the add and the read: the next delivery gets it. Reporting
    # the run as held is still the right answer for this one, because it did not
    # acquire the claim and must not post.
    return holder if holder is not None else "an expired run"


def renew_run_claim(connection_id: str, task_id: str) -> None:
    """Extend this run's claim, refusing to continue if it is no longer ours.

    Opus: Losing the claim mid-run means it expired and another run may now be writing
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
