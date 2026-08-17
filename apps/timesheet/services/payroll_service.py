"""Xero Payroll pay-run surface behind ``/api/timesheets/payroll/...``.

Pay-run reads come from the local ``XeroPayRun`` mirror; everything that talks
to the accounting system goes through ``get_provider()``. ``apps.xero`` sits
ABOVE the domain apps in the import contract, so this module cannot import it
— the registry is the inversion that lets a domain service drive an
integration (ADR 0012), and it is also what swaps in the write-suppressing
provider under ``XERO_READONLY``.

``XeroPayRun`` itself is reached through Django's app registry behind a
protocol, the pattern ``apps/core/models.py`` uses for ``_WageBearingStaff``.

Posting a week is asynchronous: ``start_post_week_task`` registers the run and
dispatches the Celery task that does the work, then hands back the URL of the
stream that reports it. The stream only reads (ADR 0024).
"""

import logging
import uuid as uuid_module
from collections.abc import Iterator
from datetime import date, timedelta
from decimal import Decimal
from typing import Protocol, TypedDict, cast
from uuid import UUID

from apps.accounting.registry import get_provider
from apps.accounting.types import require_payroll_week_start
from apps.core.models import CompanyDefaults
from apps.core.xero_registry import xero_model_manager
from apps.timesheet.services import payroll_progress

logger = logging.getLogger(__name__)

# Keep posting task state long enough for the client to connect to its stream.


class PayRunRow(Protocol):
    """Structural view of ``xero.XeroPayRun`` used by the pay-run list."""

    @property
    def id(self) -> UUID:
        """The mirror row's primary key."""

    @property
    def xero_id(self) -> UUID:
        """Xero's id for the pay run."""

    @property
    def period_start_date(self) -> date:
        """First day of the pay period."""

    @property
    def period_end_date(self) -> date:
        """Last day of the pay period."""

    @property
    def payment_date(self) -> date:
        """The date staff are paid."""

    @property
    def pay_run_status(self) -> str:
        """Xero's pay-run status (Draft, Posted, ...)."""


class _PayRunQuery(Protocol):
    """The queryset surface the pay-run list needs (ordering + iteration)."""

    def order_by(self, *fields: str) -> "_PayRunQuery":
        """Return the rows re-ordered by the given fields."""

    def first(self) -> PayRunRow | None:
        """Return the first row, or None when empty."""

    def __iter__(self) -> Iterator[PayRunRow]:
        """Iterate the matched rows."""


class _PayRunMirror(Protocol):
    """The manager surface the pay-run list needs off the XeroPayRun model."""

    def filter(self, **kwargs: object) -> _PayRunQuery:
        """Return the mirror rows matching the given lookups."""


def _pay_run_mirror() -> _PayRunMirror:
    """Narrow the shared xero-registry seam to this module's protocol."""
    return cast("_PayRunMirror", xero_model_manager("XeroPayRun"))


class PayRunData(TypedDict):
    """Data contract for PayRunData."""

    id: UUID
    xero_id: UUID
    period_start_date: date
    period_end_date: date
    payment_date: date
    pay_run_status: str
    xero_url: str


class PayRunListData(TypedDict):
    """Data contract for PayRunListData."""

    pay_runs: list[PayRunData]
    next_postable_week_start_date: date | None
    next_postable_week_end_date: date | None


class PayRunSyncData(TypedDict):
    """Data contract for PayRunSyncData."""

    synced: bool
    fetched: int
    created: int
    updated: int


class CreatedPayRunData(TypedDict):
    """Data contract for CreatedPayRunData."""

    id: UUID
    xero_id: UUID
    status: str
    period_start_date: date
    period_end_date: date
    payment_date: date
    xero_url: str


class PostWeekStartData(TypedDict):
    """Data contract for PostWeekStartData."""

    task_id: UUID
    stream_url: str


class StaffWeekPostingData(TypedDict):
    """One staff member's week: what Xero holds, beside what we recorded.

    Opus: Both sides are split timesheet/leave because they travel through different
    Xero APIs and read back from different places (ADR 0007). ``matches`` is
    computed server-side so every consumer agrees on what "in sync" means.
    """

    staff_id: str
    posted: bool
    timesheet_status: str | None
    posted_timesheet_hours: Decimal
    posted_leave_hours: Decimal
    recorded_timesheet_hours: Decimal
    recorded_leave_hours: Decimal
    matches: bool


class WeekPostingStatusData(TypedDict):
    """Data contract for WeekPostingStatusData."""

    week_start_date: date
    staff: list[StaffWeekPostingData]


def build_xero_payroll_url(pay_run_xero_id: UUID) -> str:
    """Deep link to a pay run in Xero (v1 ``apps/workflow/utils.py``).

    Pure string building from the configured shortcode — no Xero call — so it
    ports now rather than waiting for Phase 4.
    """
    shortcode = CompanyDefaults.get_solo().xero_shortcode
    if not shortcode:
        raise ValueError(
            "Xero shortcode not configured. Run 'python manage.py xero --setup' to fetch it."
        )
    return f"https://payroll.xero.com/PayRun?CID={shortcode}#payruns/{pay_run_xero_id}"


def get_payroll_calendar_id() -> UUID:
    """Read the configured payroll calendar id."""
    calendar_id = CompanyDefaults.get_solo().xero_payroll_calendar_id
    if not calendar_id:
        raise ValueError(
            "xero_payroll_calendar_id not configured in CompanyDefaults. "
            "Run: python manage.py xero --setup"
        )
    return calendar_id


def next_postable_payroll_week(calendar_id: UUID) -> tuple[date, date] | None:
    """Compute the only week that can currently be posted to the payroll calendar.

    Opus: Xero processes pay runs in sequence, so it is: the open Draft pay run's
    period if there is one; otherwise the week after the latest pay run;
    otherwise the calendar's own anchor period, which only a calendar with no
    pay runs at all falls back to.

    Opus: The first two cases read the local mirror. The third asks the provider,
    and returns None rather than raising if that fails: this is a READ
    endpoint and must not die because the accounting system is unreachable.
    None is part of the field's contract — it tells the client to fall back to
    the current week.
    """
    mirror = _pay_run_mirror()
    open_draft = (
        mirror.filter(payroll_calendar_id=calendar_id, pay_run_status="Draft")
        .order_by("-period_start_date")
        .first()
    )
    if open_draft is not None:
        return open_draft.period_start_date, open_draft.period_end_date

    latest = mirror.filter(payroll_calendar_id=calendar_id).order_by("-period_end_date").first()
    if latest is not None:
        start = latest.period_end_date + timedelta(days=1)
        return start, start + timedelta(days=6)

    try:
        return get_provider().payroll_calendar_anchor_week()
    # deliberate-swallow: Opus: this is the only branch that leaves the local mirror
    # and calls the accounting system, and it serves a READ endpoint that the
    # whole weekly grid hangs off. None is already part of this field's
    # contract — the schema tells the client to fall back to the current week —
    # so an unreachable provider degrades one panel instead of emptying the
    # screen.
    except Exception:
        logger.warning(
            "Payroll calendar %s has no pay runs and its anchor week could not be read; "
            "reporting no postable week.",
            calendar_id,
            exc_info=True,
        )
        return None


def list_pay_runs() -> PayRunListData:
    """All pay runs on the configured calendar, newest first."""
    calendar_id = get_payroll_calendar_id()
    pay_runs = (
        _pay_run_mirror().filter(payroll_calendar_id=calendar_id).order_by("-period_end_date")
    )
    postable = next_postable_payroll_week(calendar_id)
    return {
        "pay_runs": [
            {
                "id": pay_run.id,
                "xero_id": pay_run.xero_id,
                "period_start_date": pay_run.period_start_date,
                "period_end_date": pay_run.period_end_date,
                "payment_date": pay_run.payment_date,
                "pay_run_status": pay_run.pay_run_status,
                "xero_url": build_xero_payroll_url(pay_run.xero_id),
            }
            for pay_run in pay_runs
        ],
        "next_postable_week_start_date": postable[0] if postable else None,
        "next_postable_week_end_date": postable[1] if postable else None,
    }


def create_pay_run_for_week(week_start_date: date) -> CreatedPayRunData:
    """Create the week's Draft pay run and shape it for the wire.

    Opus: Named for the week rather than matching the provider method it calls: this
    one validates the Monday and builds the response, the provider's talks to
    the accounting system.
    """
    require_payroll_week_start(week_start_date)
    created = get_provider().create_pay_run(week_start_date)
    return {
        "id": UUID(created.pay_run_id),
        "xero_id": UUID(created.pay_run_id),
        "status": created.pay_run_status,
        "period_start_date": created.period_start_date,
        "period_end_date": created.period_end_date,
        "payment_date": created.payment_date,
        "xero_url": build_xero_payroll_url(UUID(created.pay_run_id)),
    }


def refresh_pay_run_mirror() -> PayRunSyncData:
    """Re-sync the local pay-run mirror and shape the counts for the wire."""
    result = get_provider().refresh_pay_runs()
    return {
        "synced": True,
        "fetched": result.fetched,
        "created": result.created,
        "updated": result.updated,
    }


def posting_status_for_week(week_start_date: date) -> WeekPostingStatusData:
    """Report what Xero holds for the week, beside what the timesheet recorded.

    Opus: Its own endpoint rather than a field on the weekly overview: this one asks
    Xero live, and folding it into the grid's read would stop the grid
    rendering whenever Xero is unreachable (ADR 0007).

    Opus: No try/except. An operator comparing payroll figures must not be shown
    zeros because the call failed — a silent zero here reads as "nothing was
    posted", which is the one answer that would make them post again.
    """
    require_payroll_week_start(week_start_date)
    return {
        "week_start_date": week_start_date,
        "staff": [
            {
                "staff_id": row.staff_id,
                "posted": row.posted,
                "timesheet_status": row.timesheet_status,
                "posted_timesheet_hours": row.posted_timesheet_hours,
                "posted_leave_hours": row.posted_leave_hours,
                "recorded_timesheet_hours": row.recorded_timesheet_hours,
                "recorded_leave_hours": row.recorded_leave_hours,
                "matches": row.matches,
            }
            for row in get_provider().week_posting_status(week_start_date)
        ],
    }


def start_post_week_task(staff_ids: list[UUID], week_start_date: date) -> PostWeekStartData:
    """Register a payroll-posting run, dispatch it, and hand back its stream URL.

    Opus: The work happens in a Celery task, not in the stream that reports it: the
    stream is a GET and a GET never writes, and a task that outlives the
    client's connection is what makes a dropped connection recoverable rather
    than a lost record of what was posted.
    """
    if not staff_ids:
        raise ValueError("staff_ids is required")
    require_payroll_week_start(week_start_date)

    task_id = uuid_module.uuid4()
    payroll_progress.register(
        str(task_id), [str(staff_id) for staff_id in staff_ids], week_start_date.isoformat()
    )
    # Opus: Call-time import: apps.timesheet.tasks imports the accounting registry,
    # which this module is itself imported by at app-ready.
    from apps.timesheet.tasks import post_payroll_week_task  # noqa: PLC0415

    try:
        post_payroll_week_task.delay(
            str(task_id), [str(staff_id) for staff_id in staff_ids], week_start_date.isoformat()
        )
    except Exception as exc:
        # Opus: Registering the run before dispatching it is what makes the stream
        # connectable immediately; it also means a broker that refuses the
        # dispatch leaves a registered run that nothing will ever publish to.
        # The stream cannot tell that from a slow post, so it would spin for
        # its full 1800s timeout — the exact failure this module's docstring
        # says the design removes. Publishing the terminal event here is the
        # only place that knows the work never started.
        payroll_progress.publish(
            str(task_id),
            {"event": "error", "message": f"Could not start the posting run: {exc}"},
        )
        payroll_progress.publish(
            str(task_id), {"event": "done", "successful": 0, "failed": len(staff_ids)}
        )
        raise
    logger.info(
        "Dispatched payroll posting task %s for %d staff, week %s",
        task_id,
        len(staff_ids),
        week_start_date,
    )
    return {
        "task_id": task_id,
        "stream_url": f"/api/timesheets/payroll/post-staff-week/stream/{task_id}/",
    }
