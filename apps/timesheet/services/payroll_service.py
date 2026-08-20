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
from typing import TYPE_CHECKING, Protocol, TypedDict, cast
from uuid import UUID

from apps.accounting.registry import get_provider
from apps.accounting.types import require_payroll_week_start
from apps.accounts.staff_directory import get_displayable_staff
from apps.core.errors import ConflictError
from apps.core.models import CompanyDefaults
from apps.core.xero_registry import xero_model_manager
from apps.timesheet.services import payroll_runs

if TYPE_CHECKING:
    from django.db.models import QuerySet

    from apps.accounts.models import Staff
    from apps.timesheet.schemas import PayrollPostRunOut, PayrollRunsOut

logger = logging.getLogger(__name__)


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


class PayrollRunInProgressError(ConflictError):
    """Another payroll posting run already holds this organisation's calendar.

    Opus: A typed refusal so the boundary answers 409 with the message verbatim
    (apps/core/envelope.py). It used to be reported by inventing a run, writing a
    fabricated failure into it and making the client open a stream to discover
    it had been refused — a refusal that had to be subscribed to.
    """


class PostWeekStartData(TypedDict):
    """Data contract for PostWeekStartData."""

    #: Opus: The run's opening document, not a task id and a stream URL. The panel
    #: renders "0 of N" from it before any push arrives, and the stream path is a
    #: client constant — a URL was never the contract.
    #: Fable: Held as the schema itself, not `model_dump`ed to `dict[str, Any]`:
    #: the wire contract (`PostWeekToXeroStartResponse.run`) is typed, and ninja
    #: serialises the model — dumping here only erased the type between two
    #: typed ends.
    run: "PayrollPostRunOut"


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
    pay_basis: str | None
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

    The first two cases read the local mirror. The third asks the provider,
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


def posting_status_for_week(week_start_date: date) -> WeekPostingStatusData:
    """Report what Xero holds for the week, beside what the timesheet recorded.

    Opus: Its own endpoint rather than a field on the weekly overview: this one asks
    Xero live, and folding it into the grid's read would stop the grid
    rendering whenever Xero is unreachable (ADR 0007).

    No try/except. An operator comparing payroll figures must not be shown
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
                "pay_basis": row.pay_basis,
                "matches": row.matches,
            }
            for row in get_provider().week_posting_status(week_start_date)
        ],
    }


def current_runs() -> "PayrollRunsOut":
    """Every payroll run this organisation has state for.

    Opus: Reads the connection id rather than taking one, so the page needs to
    know nothing but its own week — the run is keyed by calendar, not by an id
    the client had to still be holding. That is what makes a reload rejoin.
    """
    return payroll_runs.read_runs(get_provider().payroll_connection_id())


def _postable_staff(week_start_date: date) -> "QuerySet[Staff]":
    """Return the staff a week's posting covers.

    The same filter the weekly grid and ``week_posting_status`` answer from,
    so the roster the panel shows, the roster the status compares, and the
    roster the post covers are one list (ADR 0039).
    """
    return get_displayable_staff(date_range=(week_start_date, week_start_date + timedelta(days=6)))


def start_post_week_task(week_start_date: date) -> PostWeekStartData:
    """Claim the calendar, refuse a wrong week on fresh data, and dispatch the work.

    Opus: The work happens in a Celery task, not in the stream that reports it: a
    GET never writes, and a task that outlives the client's connection is what
    makes a dropped connection recoverable rather than a lost record of what was
    posted.

    Opus: The CLAIM is taken here rather than inside the task. A second operator
    click is then refused synchronously, with a 409 naming the live run, instead
    of being handed a run id whose only content is a fabricated failure it has
    to open a stream to read. Redelivery of a dead worker's message is still the
    task's problem and is still checked there (ADR 0024).

    Fable: The week is the whole request. The staff are derived HERE, from the
    same ``get_displayable_staff(date_range=...)`` filter the weekly grid and
    ``week_posting_status`` use — the client used to relay the grid's staff ids
    back at us, so a grid loaded before a staff change posted a stale roster.

    Fable: The postable-week rule is enforced here, on a mirror refreshed
    INSIDE this request (a POST may write; the panel's GET may not), so the
    refusal is cheap, current, and owned by the server. The panel's banner may
    be an hour stale; this check cannot be. When the calendar has no runs and
    the provider cannot name its anchor week, Xero itself remains the arbiter —
    posting proceeds and the create is refused there if the period is wrong.
    """
    require_payroll_week_start(week_start_date)

    provider = get_provider()
    connection_id = provider.payroll_connection_id()
    run_id = uuid_module.uuid4()
    holder = payroll_runs.acquire_run_claim(connection_id, str(run_id))
    if holder is not None:
        raise PayrollRunInProgressError(
            f"A payroll posting run ({holder}) is already in progress for this "
            "organisation. Nothing was posted. Wait for it to finish, then check "
            "what Xero holds before posting again."
        )

    # Fable: Preflight refusals happen under the claim — refreshing the mirror
    # concurrently with a live run's own refresh would have two writers
    # deleting and recreating the same rows — and release it on the way out,
    # writing no run document: a refused week never started.
    try:
        provider.refresh_pay_runs()
        postable = next_postable_payroll_week(get_payroll_calendar_id())
        if postable is not None and week_start_date != postable[0]:
            raise ValueError(
                f"Xero processes pay runs in order: only the week starting "
                f"{postable[0].isoformat()} can be posted next. Nothing was posted."
            )
        staff_ids = [staff.id for staff in _postable_staff(week_start_date)]
        if not staff_ids:
            raise ValueError("There are no staff to post for this week.")
    except Exception:
        payroll_runs.release_run_claim(connection_id, str(run_id))
        raise

    run = payroll_runs.running(connection_id, str(run_id), week_start_date, total=len(staff_ids))
    # Opus: Call-time import: apps.timesheet.tasks imports the accounting registry,
    # which this module is itself imported by at app-ready.
    from apps.timesheet.tasks import post_payroll_week_task  # noqa: PLC0415

    try:
        post_payroll_week_task.delay(
            str(run_id),
            connection_id,
            [str(staff_id) for staff_id in staff_ids],
            week_start_date.isoformat(),
        )
    except Exception as exc:
        # Opus: A broker that refuses the dispatch leaves a run nothing will ever
        # advance. Closing it here is the only place that knows the work never
        # started — and releasing the claim matters as much, or the refusal would
        # block payroll until the claim's TTL expired.
        payroll_runs.write(
            connection_id,
            payroll_runs.finished(run, "failed", message=f"Could not start the posting run: {exc}"),
        )
        payroll_runs.release_run_claim(connection_id, str(run_id))
        raise
    logger.info(
        "Dispatched payroll posting run %s for %d staff, week %s",
        run_id,
        len(staff_ids),
        week_start_date,
    )
    return {"run": run}
