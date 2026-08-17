"""Posting a week of timesheet hours to Xero Payroll NZ.

The write half of v1's ``apps/workflow/api/xero/payroll.py`` (the read half is
``payroll_sync``, the setup half ``payroll_setup``). ADR 0007 is the routing
rule; the behaviours below were each established against the live API and are
the reason this is not a thin wrapper.

**The order of operations is load-bearing.** ``post_payroll_week`` runs, in
this order and before it yields anything:

1. validate that every line in the week carries a pay item with a Xero id —
   fail-early, so a misconfigured week makes no partial API calls;
2. reconcile leave, which MUST happen before the pay run exists: Xero locks
   leave deletion once the employee is in a draft pay run (KAN-326);
3. ensure the Draft pay run;
4. fetch every existing timesheet for the week in ONE call.

**Two APIs, one week.** ``XeroPayItem.uses_leave_api`` routes each line: leave
types go to the Employee Leave API, because only that surface debits the leave
balance; work and any leave paid as an earnings rate go to the Timesheets API.

**Posting replaces, never appends.** An existing timesheet is deleted and
recreated, so Xero stays the source of truth for what was posted. Nothing
local records "posted" — ask Xero instead (ADR 0007).
"""
# Opus: docstring rationale unratified (ADR 0051).

import logging
import time
from collections import Counter, defaultdict
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

from xero_python.payrollnz import (
    PayrollNzApi,
    PayRun,
    Timesheet,
    TimesheetLine,
)

from apps.accounting.types import (
    PayRunRef,
    PayRunSyncResult,
    StaffWeekPosting,
    StaffWeekPostResult,
    require_payroll_week_start,
)
from apps.accounts.models import Staff
from apps.accounts.staff_directory import get_displayable_staff
from apps.core.errors import AppErrorContext, persist_app_error
from apps.core.models import CompanyDefaults
from apps.job.models.costing import CostLine
from apps.timesheet.services import hour_categories
from apps.xero import payroll_sdk as _payroll_sdk  # noqa: F401 -- applies v1 SDK fixes
from apps.xero.auth import get_api_client, get_tenant_id
from apps.xero.helpers import as_date
from apps.xero.models import XeroPayRun
from apps.xero.payroll_leave import posted_leave_hours, reconcile_leave_for_staff_week
from apps.xero.payroll_setup import get_payroll_calendars
from apps.xero.payroll_sync import get_pay_runs_for_sync
from apps.xero.transforms import transform_pay_run

if TYPE_CHECKING:
    from apps.xero.models import XeroPayItem

logger = logging.getLogger(__name__)

# Opus: Xero's payroll endpoints rate-limit hard, and a posting run makes several
# mutating calls per employee. v1 measured 3s as the interval that survives a
# full staff list without throttling.
SLEEP_SECONDS = 3
# Opus: Xero pays the whole period end + 3 days (the Wednesday after a Sunday end).
PAYMENT_OFFSET_DAYS = 3
#: Opus: The precision payroll units are held and compared at, matching the leave
#: side (payroll_leave.LEAVE_UNIT_PRECISION) so one notion of "a payroll unit"
#: covers both surfaces.
UNIT_PRECISION = Decimal("0.001")
#: Opus: The two timesheet statuses this code acts on. Anything else means Xero has
#: moved the timesheet beyond our reach — paid — and it is refused rather than
#: modified.
STATUS_DRAFT = "Draft"
STATUS_APPROVED = "Approved"


# Opus: docstring rationale unratified (ADR 0051).
@dataclass(frozen=True)
class TimesheetLinePayload:
    """One aggregated timesheet line, in the units the domain holds them in.

    Decimal rather than float all the way to the SDK call, which is the only
    place a float is unavoidable.
    """

    date: date
    earnings_rate_id: str
    units: Decimal


# Opus: docstring rationale unratified (ADR 0051).
@dataclass(frozen=True)
class PostedTimesheet:
    """What Xero's timesheet LIST can be trusted for.

    Deliberately not the SDK's ``Timesheet``: that endpoint returns each line
    WITHOUT its date, and the generated setter refuses None, so the typed call
    cannot represent the payload at all once a week has been posted. It also
    means the lines it does return are unusable for comparison — anything that
    needs them fetches the timesheet detail instead.

    ``totalHours`` is deliberately NOT carried. Xero reports it as 0 for a
    timesheet it has just accepted and fills it in later, so a field here would
    be a trap for the next reader; hours come from the detail lines.
    """

    timesheet_id: str
    employee_id: str
    status: str


@dataclass(frozen=True)
class _WeekWindow:
    """The payroll week being posted."""

    start: date
    end: date

    @classmethod
    def of(cls, week_start_date: date) -> "_WeekWindow":
        """Build the Monday-to-Sunday window, refusing any other start day."""
        require_payroll_week_start(week_start_date)
        return cls(start=week_start_date, end=week_start_date + timedelta(days=6))


def _payroll_api() -> PayrollNzApi:
    """Build the Payroll NZ client for the connected tenant."""
    return PayrollNzApi(get_api_client())


def _tenant() -> str:
    """Return the connected tenant id, refusing an unconfigured install."""
    tenant_id = get_tenant_id()
    if not tenant_id:
        raise ValueError("No Xero tenant ID configured for payroll posting")
    return str(tenant_id)


# Opus: docstring rationale unratified (ADR 0051).
def _week_time_lines(week: _WeekWindow, staff_ids: Sequence[UUID] | None = None) -> list[CostLine]:
    """Every actual time line in the week, optionally narrowed to some staff.

    Only actual lines are worked time — an estimate or quote line describes
    hypothetical hours and must never reach payroll.
    """
    lines = CostLine.objects.filter(
        cost_set__kind="actual",
        kind="time",
        accounting_date__gte=week.start,
        accounting_date__lte=week.end,
    ).select_related("xero_pay_item")
    if staff_ids is not None:
        lines = lines.filter(staff_id__in=list(staff_ids))
    return list(lines)


# Opus: docstring rationale unratified (ADR 0051).
def validate_pay_items_for_week(staff_ids: Sequence[UUID], week_start_date: date) -> None:
    """Refuse the whole week unless every line can name a Xero earnings rate or leave type.

    Checked up front for all staff at once: a line discovered mid-run would
    leave some employees posted and others not, which is the state that is
    expensive to reason about afterwards.
    """
    week = _WeekWindow.of(week_start_date)
    problems = [
        f"CostLine {line.id} has no xero_pay_item"
        if line.xero_pay_item is None
        else f"CostLine {line.id} has XeroPayItem {line.xero_pay_item.name!r} with no xero_id"
        for line in _week_time_lines(week, staff_ids)
        if line.xero_pay_item is None or not line.xero_pay_item.xero_id
    ]
    if problems:
        raise ValueError(
            "Payroll pay items are not linked to Xero — run "
            "'python manage.py xero --configure-payroll' first:\n"
            + "\n".join(f"  - {problem}" for problem in problems)
        )


def _pay_item(line: CostLine) -> "XeroPayItem":
    """Return the line's pay item, already proved present by validate_pay_items_for_week."""
    if line.xero_pay_item is None:
        raise ValueError(f"CostLine {line.id} has no xero_pay_item")
    return line.xero_pay_item


# Opus: docstring rationale unratified (ADR 0051).
def _split_by_api(lines: Sequence[CostLine]) -> tuple[list[CostLine], list[CostLine]]:
    """Split lines into (leave-API lines, timesheet-API lines) by their pay item.

    The predicate is ``hour_categories.is_leave`` rather than a local
    ``uses_leave_api`` read. They were the same test written twice, which is
    the shape v1's three drifting leave rules started as (ADR 0007, ADR 0039):
    the timesheet screens and the payroll push must agree on what leave is, or
    the hours a page shows as leave are not the hours Xero receives as leave.
    """
    leave_lines: list[CostLine] = []
    timesheet_lines: list[CostLine] = []
    for line in lines:
        if hour_categories.is_leave(line):
            leave_lines.append(line)
        else:
            timesheet_lines.append(line)
    return leave_lines, timesheet_lines


# Opus: docstring rationale unratified (ADR 0051).
def _timesheet_line_payloads(lines: Sequence[CostLine]) -> list[TimesheetLinePayload]:
    """Aggregate lines into one timesheet line per (date, earnings rate).

    Accumulated in Decimal, the type ``CostLine.quantity`` already is. Summing
    these as floats put binary rounding error into the hours a person is paid
    for, and the comparison below then hid it by rounding to 2dp.
    """
    totals: defaultdict[tuple[date, str], Decimal] = defaultdict(lambda: Decimal("0"))
    for line in lines:
        totals[(line.accounting_date, str(_pay_item(line).xero_id))] += line.quantity
    return [
        TimesheetLinePayload(
            date=entry_date, earnings_rate_id=rate_id, units=units.quantize(UNIT_PRECISION)
        )
        for (entry_date, rate_id), units in totals.items()
    ]


# Opus: docstring rationale unratified (ADR 0051).
def _lines_match(
    existing_lines: Sequence[TimesheetLinePayload], new_lines: Sequence[TimesheetLinePayload]
) -> bool:
    """Whether Xero already holds exactly these lines.

    Comparing before writing turns a re-post of unchanged hours into a no-op,
    which matters because the alternative is delete-and-recreate. Both sides
    are already quantized to the same payroll-unit precision when they are
    built, so this is a plain equality rather than a rounding that absorbs
    error we introduced ourselves.

    Multiset, not set: set equality made ``[line, line]`` equal ``[line]``, so
    a duplicated date-and-rate line in Xero read as an exact match and the
    extra payable hours were left in place. We never create duplicates — the
    payload is aggregated per (date, rate) — but Xero is edited by people too,
    and "already correct" is the one answer that writes nothing.
    """
    return Counter(existing_lines) == Counter(new_lines)


# Opus: docstring rationale unratified (ADR 0051).
def post_timesheet(
    employee_id: UUID,
    week: _WeekWindow,
    line_payloads: Sequence[TimesheetLinePayload],
    existing_timesheet: PostedTimesheet | None,
) -> Any:
    """Replace the employee's timesheet for the week, then approve it.

    Delete-and-recreate rather than editing lines: it is one call instead of
    one per line, and it leaves no line behind that the new hours did not
    account for. An empty week still posts an empty timesheet — without one,
    Xero falls back to the employee's pay template (40 hours). Xero rejects
    zero-unit lines but accepts a timesheet with no lines at all.
    """
    tenant_id = _tenant()
    api = _payroll_api()

    if existing_timesheet is not None and _lines_match(
        timesheet_lines(existing_timesheet.timesheet_id), line_payloads
    ):
        # Opus: Matching lines are not enough — an unapproved timesheet is not a
        # posted one. A create that succeeded followed by a failed
        # approve_timesheet leaves a Draft carrying exactly the right hours,
        # and the operator's retry used to match it, return here, and report a
        # clean success for a timesheet nobody ever approved. The same happens
        # after someone reverts an Approved sheet in Xero and re-posts.
        if existing_timesheet.status == STATUS_APPROVED:
            logger.info(
                "Timesheet %s already matches the hours to post; leaving it alone",
                existing_timesheet.timesheet_id,
            )
            return existing_timesheet
        if existing_timesheet.status == STATUS_DRAFT:
            logger.warning(
                "Timesheet %s holds the right hours but is still Draft; approving it",
                existing_timesheet.timesheet_id,
            )
            api.approve_timesheet(
                xero_tenant_id=tenant_id, timesheet_id=existing_timesheet.timesheet_id
            )
            time.sleep(SLEEP_SECONDS)
            return PostedTimesheet(
                timesheet_id=existing_timesheet.timesheet_id,
                employee_id=existing_timesheet.employee_id,
                status=STATUS_APPROVED,
            )
        # Opus: Any other status is paid; _delete_timesheet owns that refusal.

    if existing_timesheet is not None:
        _delete_timesheet(api, tenant_id, existing_timesheet)

    created = api.create_timesheet(
        xero_tenant_id=tenant_id,
        timesheet=Timesheet(
            employee_id=str(employee_id),
            payroll_calendar_id=str(_calendar_id()),
            start_date=week.start,
            end_date=week.end,
            timesheet_lines=[
                TimesheetLine(
                    date=payload.date,
                    earnings_rate_id=payload.earnings_rate_id,
                    # Opus: The one place a float is unavoidable: the SDK's own field.
                    number_of_units=float(payload.units),
                )
                for payload in line_payloads
            ],
        ),
    )
    time.sleep(SLEEP_SECONDS)
    if not created or not created.timesheet:
        raise ValueError(f"Xero returned no timesheet when creating one for {employee_id}")

    timesheet = created.timesheet
    api.approve_timesheet(xero_tenant_id=tenant_id, timesheet_id=str(timesheet.timesheet_id))
    time.sleep(SLEEP_SECONDS)
    logger.info(
        "Posted timesheet %s for employee %s with %d line(s)",
        timesheet.timesheet_id,
        employee_id,
        len(line_payloads),
    )
    return timesheet


def _delete_timesheet(api: PayrollNzApi, tenant_id: str, existing: PostedTimesheet) -> None:
    """Clear an existing timesheet, reverting it from Approved first if needed."""
    timesheet_id = existing.timesheet_id
    if existing.status == STATUS_APPROVED:
        api.revert_timesheet(xero_tenant_id=tenant_id, timesheet_id=timesheet_id)
        time.sleep(SLEEP_SECONDS)
    elif existing.status != STATUS_DRAFT:
        # Opus: Paid is the case that matters: the money has left, so silently
        # replacing the record would hide a discrepancy rather than fix one.
        raise ValueError(
            f"Timesheet {timesheet_id} is {existing.status!r} and cannot be modified — "
            "it has already been paid. Correct it in Xero."
        )
    api.delete_timesheet(xero_tenant_id=tenant_id, timesheet_id=timesheet_id)
    time.sleep(SLEEP_SECONDS)


# Opus: docstring rationale unratified (ADR 0051).
def existing_timesheets_for_week(week: _WeekWindow) -> dict[str, PostedTimesheet]:
    """Every timesheet Xero already holds for the week, keyed by employee id.

    One call for the whole batch; the per-employee alternative multiplied the
    posting run's API calls by the size of the staff list. Identity, status and
    total only — see PostedTimesheet for why the lines this endpoint returns
    are not usable.
    """
    response = _payroll_api().get_timesheets(
        xero_tenant_id=_tenant(),
        start_date=week.start,
        end_date=week.end,
    )
    if response is None:
        raise ValueError(f"Xero returned no timesheets for the week of {week.start}")
    found: dict[str, PostedTimesheet] = {}
    for timesheet in response.timesheets or []:
        start_date = as_date(timesheet.start_date)
        if start_date != week.start:
            continue
        if not timesheet.timesheet_id or not timesheet.employee_id or not timesheet.status:
            raise ValueError("Xero returned a timesheet without id, employee id, or status")
        employee_id = str(timesheet.employee_id)
        # Opus: Refused rather than last-one-wins. A dict comprehension quietly kept
        # the final row, and the one it dropped stayed in Xero — invisible to
        # the match check and to the reconciliation, while still paying. One
        # employee cannot hold two timesheets for one week by any route this
        # code takes, so seeing two means something else wrote one.
        if employee_id in found:
            raise ValueError(
                f"Xero holds two timesheets for employee {employee_id} in the week of "
                f"{week.start}: {found[employee_id].timesheet_id} and "
                f"{timesheet.timesheet_id}. Resolve it in Xero before posting."
            )
        found[employee_id] = PostedTimesheet(
            timesheet_id=str(timesheet.timesheet_id),
            employee_id=employee_id,
            status=str(timesheet.status),
        )
    return found


# Opus: docstring rationale unratified (ADR 0051).
def timesheet_lines(timesheet_id: str) -> list[TimesheetLinePayload]:
    """Fetch the lines Xero holds on one timesheet, in the same shape we send.

    Raw JSON because the SDK's generated setter refuses a null line date, and
    the LIST endpoint omits dates — so the typed call cannot read back a
    timesheet once it has been posted. The detail endpoint does carry them,
    which is why hours read back from here can be compared at all.

    Returning our own payload type rather than SDK objects is what lets
    ``_lines_match`` compare like with like instead of translating at the
    comparison.

    A null date here is refused rather than skipped. v1 recorded the cause —
    Xero returns nulls for date, earnings rate and units **after a timesheet is
    deleted** — so a null means we are reading a timesheet that no longer
    exists, not a line to leave out. Skipping them understated the hours Xero
    holds, which reads as a mismatch, which deletes and recreates a timesheet
    that was already correct.
    """
    response = _payroll_api().get_timesheet(xero_tenant_id=_tenant(), timesheet_id=timesheet_id)
    timesheet = response.timesheet if response else None
    if timesheet is None:
        raise ValueError(f"Xero returned no timesheet for {timesheet_id}")
    lines = timesheet.timesheet_lines or []
    incomplete = [
        line
        for line in lines
        if line.date is None or line.earnings_rate_id is None or line.number_of_units is None
    ]
    if incomplete:
        raise ValueError(
            f"Xero returned {len(incomplete)} incomplete line(s) on timesheet "
            f"{timesheet_id}. Xero does that for a DELETED timesheet, so the hours it "
            "holds cannot be read from this response."
        )
    payloads: list[TimesheetLinePayload] = []
    for line in lines:
        line_date = as_date(line.date)
        if line_date is None:
            raise ValueError(f"Xero returned an unreadable line date on timesheet {timesheet_id}")
        payloads.append(
            TimesheetLinePayload(
                date=line_date,
                earnings_rate_id=str(line.earnings_rate_id),
                units=Decimal(str(line.number_of_units)).quantize(UNIT_PRECISION),
            )
        )
    return payloads


# --- Pay runs ------------------------------------------------------------


def _calendar_id() -> UUID:
    """Return the configured payroll calendar, refusing an unconfigured install."""
    calendar_id = CompanyDefaults.get_solo().xero_payroll_calendar_id
    if not calendar_id:
        raise ValueError(
            "xero_payroll_calendar_id is not configured. Run 'python manage.py xero --setup' first."
        )
    return calendar_id


# Opus: docstring rationale unratified (ADR 0051).
def payroll_calendar_anchor_week() -> tuple[date, date] | None:
    """Return the calendar's own first postable period, when it holds no pay runs yet.

    A calendar's reported period advances as pay runs are processed, so with
    none it still reports its anchor.
    """
    calendar_id = str(_calendar_id())
    for calendar in get_payroll_calendars():
        if str(calendar.id) == calendar_id:
            return calendar.period_start_date, calendar.period_end_date
    return None


def create_pay_run(week_start_date: date) -> PayRunRef:
    """Create a Draft pay run for the week and mirror it locally."""
    week = _WeekWindow.of(week_start_date)
    defaults = CompanyDefaults.get_solo()
    calendar_name = defaults.xero_payroll_calendar_name
    if not calendar_name:
        raise ValueError("xero_payroll_calendar_name is not configured in CompanyDefaults")

    calendars = get_payroll_calendars()
    calendar = next((c for c in calendars if c.name == calendar_name), None)
    if calendar is None:
        raise ValueError(
            f"Payroll calendar {calendar_name!r} was not found in Xero. "
            f"Available: {sorted(c.name for c in calendars)}"
        )

    response = _payroll_api().create_pay_run(
        xero_tenant_id=_tenant(),
        pay_run=PayRun(
            payroll_calendar_id=calendar.id,
            period_start_date=week.start,
            period_end_date=week.end,
            payment_date=week.end + timedelta(days=PAYMENT_OFFSET_DAYS),
            pay_run_status="Draft",
            pay_run_type="Scheduled",
        ),
    )
    if not response or not response.pay_run:
        raise ValueError(f"Xero returned no pay run when creating one for week {week.start}")

    created = response.pay_run
    actual_start, actual_end = as_date(created.period_start_date), as_date(created.period_end_date)
    if actual_start != week.start or actual_end != week.end:
        # Opus: Xero creates the calendar's next unprocessed period regardless of the
        # dates asked for. The run now EXISTS in Xero, so mirror it before
        # bailing — otherwise the next attempt tries to create a second draft
        # and hits Xero's one-draft-per-calendar refusal with no local trace of
        # why.
        transform_pay_run(created, str(created.pay_run_id))
        raise ValueError(
            f"Xero created a pay run for {actual_start} to {actual_end} on calendar "
            f"{calendar_name!r} instead of the requested {week.start} to {week.end}. "
            "Posting requires the calendar period to match the selected week exactly."
        )

    detail = _payroll_api().get_pay_run(
        xero_tenant_id=_tenant(), pay_run_id=str(created.pay_run_id)
    )
    fetched = detail.pay_run if detail else None
    if fetched is None:
        raise ValueError(f"Xero created pay run {created.pay_run_id} but did not return its detail")
    mirrored, _ = transform_pay_run(fetched, str(created.pay_run_id))
    return _pay_run_ref(mirrored, str(created.pay_run_id))


def _pay_run_ref(pay_run: XeroPayRun, pay_run_id: str) -> PayRunRef:
    """Shape a mirrored pay run as the provider-agnostic reference."""
    return PayRunRef(
        pay_run_id=pay_run_id,
        payroll_calendar_id=str(pay_run.payroll_calendar_id),
        period_start_date=pay_run.period_start_date,
        period_end_date=pay_run.period_end_date,
        payment_date=pay_run.payment_date,
        pay_run_status=pay_run.pay_run_status or "Draft",
        pay_run_type=pay_run.pay_run_type or "Scheduled",
    )


def find_live_pay_run_for_week(week_start_date: date) -> PayRunRef | None:
    """Return the pay run Xero holds covering the week, or None — never creating one.

    The read-only counterpart to ``ensure_pay_run_for_week``. Separate rather
    than a flag on it because the reconciliation is reached from a GET, and a
    GET that creates a pay run in Xero would make opening a report a payroll
    mutation (the rule ``CompanyDefaults.get_solo`` exists to enforce
    elsewhere). It also does not refresh the local mirror, which is a write.

    Asked of Xero rather than the mirror, and matched by OVERLAP rather than
    equality: Xero's pay periods run Sunday to Saturday while a Docketworks
    week is Monday to Sunday, and ``create_pay_run`` records that Xero may
    return a different period than the one requested. An equality match reports
    "no pay run" for a week Xero is actively paying.

    Not restricted to Draft: the point is to report on the week whether its run
    is still open or already Posted.
    """
    week = _WeekWindow.of(week_start_date)
    calendar_id = str(_calendar_id())
    for pay_run in get_pay_runs_for_sync().pay_runs:
        if str(pay_run.payroll_calendar_id) != calendar_id:
            continue
        period_start, period_end = (
            as_date(pay_run.period_start_date),
            as_date(pay_run.period_end_date),
        )
        if period_start is None or period_end is None:
            raise ValueError(f"Xero pay run {pay_run.pay_run_id} has no period dates")
        if period_start <= week.end and period_end >= week.start:
            payment_date = as_date(pay_run.payment_date)
            if payment_date is None:
                raise ValueError(f"Xero pay run {pay_run.pay_run_id} has no payment date")
            # Opus: Built straight from the response, NOT through
            # transform_pay_run: that mirrors the run into XeroPayRun, and this
            # runs on a GET.
            return PayRunRef(
                pay_run_id=str(pay_run.pay_run_id),
                payroll_calendar_id=calendar_id,
                period_start_date=period_start,
                period_end_date=period_end,
                payment_date=payment_date,
                pay_run_status=str(pay_run.pay_run_status or "Draft"),
                pay_run_type=str(pay_run.pay_run_type or "Scheduled"),
            )
    return None


# Opus: docstring rationale unratified (ADR 0051).
def ensure_pay_run_for_week(week_start_date: date) -> PayRunRef:
    """Return the week's Draft pay run, creating it if the calendar has none.

    Xero allows exactly ONE Draft pay run per calendar, so a draft for another
    week is a hard stop naming the week that blocks — the operator has to
    finish or delete it in Xero first. A same-week draft is reused; posting
    overwrites its contents, which is the intended re-post path.
    """
    week = _WeekWindow.of(week_start_date)
    calendar_id = _calendar_id()
    open_drafts = list(
        XeroPayRun.objects.filter(
            xero_tenant_id=_tenant(),
            payroll_calendar_id=calendar_id,
            pay_run_status="Draft",
        )
    )
    same_week = next(
        (
            draft
            for draft in open_drafts
            if draft.period_start_date == week.start and draft.period_end_date == week.end
        ),
        None,
    )
    if same_week is not None:
        logger.warning(
            "Reusing draft pay run %s for week %s-%s; posting overwrites its contents",
            same_week.xero_id,
            week.start,
            week.end,
        )
        return _pay_run_ref(same_week, str(same_week.xero_id))
    if open_drafts:
        blocking = open_drafts[0]
        raise ValueError(
            f"A draft pay run for {blocking.period_start_date} to {blocking.period_end_date} "
            f"is already open on the payroll calendar, and Xero allows only one. Post or "
            f"delete it in Xero, then refresh, before posting {week.start} to {week.end}."
        )
    return create_pay_run(week.start)


# Opus: docstring rationale unratified (ADR 0051).
def refresh_pay_runs() -> PayRunSyncResult:
    """Re-sync the local pay-run mirror from Xero.

    The operator's recovery path after posting or deleting a run inside Xero,
    so it reports what actually moved rather than a bare success. Orphans are
    dropped: Xero is master for pay runs, and a run deleted there must not
    keep blocking the one-draft rule locally.
    """
    fetched = get_pay_runs_for_sync().pay_runs
    live_ids = {str(pay_run.pay_run_id) for pay_run in fetched}
    XeroPayRun.objects.filter(xero_tenant_id=_tenant()).exclude(xero_id__in=live_ids).delete()

    created = updated = 0
    for pay_run in fetched:
        _, status = transform_pay_run(pay_run, str(pay_run.pay_run_id))
        if status == "created":
            created += 1
        elif status != "unchanged":
            updated += 1
    logger.info(
        "Refreshed pay-run mirror: %d fetched, %d created, %d updated",
        len(fetched),
        created,
        updated,
    )
    return PayRunSyncResult(fetched=len(fetched), created=created, updated=updated)


# --- The posting run -----------------------------------------------------


def _staff_in_week(staff: Staff, week: _WeekWindow) -> bool:
    """Whether the staff member was employed during any of the payroll week."""
    if staff.employment_start_date > week.end:
        return False
    return not (staff.date_left is not None and staff.date_left < week.start)


def _failure_result(staff: Staff, error: str, has_entries: bool) -> StaffWeekPostResult:
    """One staff member's failure, shaped so the batch can carry on past it."""
    return StaffWeekPostResult(
        staff_id=str(staff.id),
        staff_name=staff.get_display_full_name(),
        success=False,
        has_entries=has_entries,
        error=error,
    )


# Opus: docstring rationale unratified (ADR 0051).
def _staff_failure_context(staff: Staff, week: _WeekWindow, stage: str) -> AppErrorContext:
    """Build the business context a payroll failure needs to be acted on.

    Only the context is shared. ``persist_app_error`` stays written out at each
    handler, because a reader — and the exception-handler contract test — should
    be able to see that a handler persists without following a call.
    """
    return AppErrorContext(
        app="xero",
        function="post_payroll_week",
        additional_context={
            "staff_id": str(staff.id),
            "week_start_date": week.start.isoformat(),
            "stage": stage,
        },
    )


def _skip_result(staff: Staff, reason: str, has_entries: bool) -> StaffWeekPostResult:
    """Build the result for a staff member deliberately not posted, hours still surfaced."""
    return StaffWeekPostResult(
        staff_id=str(staff.id),
        staff_name=staff.get_display_full_name(),
        success=True,
        skipped=True,
        reason=reason,
        has_entries=has_entries,
    )


# Opus: docstring rationale unratified (ADR 0051).
def post_payroll_week(
    staff_ids: Sequence[UUID], week_start_date: date
) -> Iterator[StaffWeekPostResult]:
    """Post a week of hours for the given staff, yielding each staff member's result.

    The preflight below runs BEFORE the first result is yielded, so a
    misconfigured week fails whole rather than half-posted. Its order is
    load-bearing — see the module docstring.

    Per-staff failures do not abort the batch: one employee's missing Xero link
    should not strand everyone else's hours, and the caller reports the
    failures individually so they can be fixed and re-posted.
    """
    week = _WeekWindow.of(week_start_date)
    if not staff_ids:
        raise ValueError("staff_ids is required")

    validate_pay_items_for_week(staff_ids, week.start)
    lines_by_staff = _lines_by_staff(week, staff_ids)
    staff_by_id = Staff.objects.in_bulk(list(staff_ids))

    # Opus: Resolved and deduplicated BEFORE the first Xero write, which is what the
    # docstring above promises. An unknown id used to raise from the final loop
    # instead: by then leave was reconciled, the pay run created, and — because
    # this is a generator consumed one result at a time — every staff member
    # ahead of the bad one had already had their timesheet deleted, recreated
    # and approved. "Fails whole rather than half-posted" was untrue of exactly
    # the input it was written for.
    #
    # Deduplicated for a second reason: in_bulk collapses repeats but the loops
    # below iterate the argument, so a repeated id reconciled leave twice,
    # posted twice, and double-counted the progress total — and the second pass
    # read a stale `existing`, either creating a second timesheet with no delete
    # between or acting on one just deleted, which reports a real post as failed.
    missing = [staff_id for staff_id in staff_ids if staff_id not in staff_by_id]
    if missing:
        raise ValueError(
            "Staff member(s) not found: " + ", ".join(str(staff_id) for staff_id in missing)
        )
    staff_to_post = list(dict.fromkeys(staff_ids))
    if len(staff_to_post) != len(staff_ids):
        logger.warning(
            "Posting week %s: %d duplicate staff id(s) collapsed",
            week.start,
            len(staff_ids) - len(staff_to_post),
        )

    # Opus: Leave first, and before the pay run exists: Xero locks leave changes once
    # the employee is in a draft pay run (KAN-326).
    #
    for staff_id in staff_to_post:
        staff = staff_by_id[staff_id]
        if not staff.xero_user_id or not _staff_in_week(staff, week):
            continue
        leave_lines, _ = _split_by_api(lines_by_staff.get(staff_id, []))
        reconcile_leave_for_staff_week(UUID(str(staff.xero_user_id)), leave_lines, week)

    ensure_pay_run_for_week(week.start)
    existing = existing_timesheets_for_week(week)

    for staff_id in staff_to_post:
        staff = staff_by_id[staff_id]
        yield _post_one_staff_week(staff, lines_by_staff.get(staff_id, []), week, existing)


# Opus: docstring rationale unratified (ADR 0051).
def _lines_by_staff(
    week: _WeekWindow, staff_ids: Sequence[UUID] | None = None
) -> dict[UUID, list[CostLine]]:
    """One query for the whole batch's time lines, grouped by staff member.

    ``staff_ids`` is optional for the same reason ``_week_time_lines``'s is:
    the posting run knows which staff it was asked for, and the week's status
    report wants them all. One query, one grouping, either way.
    """
    grouped: defaultdict[UUID, list[CostLine]] = defaultdict(list)
    for line in _week_time_lines(week, staff_ids):
        if line.staff_id is None:
            # Opus: The query filters on staff_id, so this cannot happen; naming it
            # keeps the grouping key honest rather than silently dropping pay.
            raise ValueError(f"Time line {line.id} in the payroll week has no staff member")
        grouped[line.staff_id].append(line)
    return grouped


def _post_one_staff_week(
    staff: Staff, lines: Sequence[CostLine], week: _WeekWindow, existing: dict[str, Any]
) -> StaffWeekPostResult:
    """Post one staff member's week, converting any failure into their own result."""
    if not _staff_in_week(staff, week):
        return _skip_result(staff, "Not employed during this week", bool(lines))
    if not staff.xero_user_id:
        return _failure_result(
            staff,
            f"{staff.get_display_full_name()} is not linked to a Xero employee. "
            "Ask an administrator to link them, then post again.",
            bool(lines),
        )

    employee_id = UUID(str(staff.xero_user_id))
    leave_lines, timesheet_lines = _split_by_api(lines)
    try:
        timesheet = post_timesheet(
            employee_id,
            week,
            _timesheet_line_payloads(timesheet_lines),
            existing.get(str(employee_id)),
        )
    except Exception as exc:  # noqa: BLE001 -- Opus: one staff member's failure becomes their own result rather than stranding the rest of the batch; it is persisted and reported, never swallowed
        persist_app_error(exc, _staff_failure_context(staff, week, "timesheet"))
        return _failure_result(staff, str(exc), bool(lines))

    work_lines = [line for line in timesheet_lines if _pay_item(line).multiplier is not None]
    other_leave_lines = [line for line in timesheet_lines if _pay_item(line).multiplier is None]
    return StaffWeekPostResult(
        staff_id=str(staff.id),
        staff_name=staff.get_display_full_name(),
        success=True,
        timesheet_id=str(timesheet.timesheet_id),
        entries_posted=len(lines),
        work_hours=sum((line.quantity for line in work_lines), Decimal("0")),
        other_leave_hours=sum((line.quantity for line in other_leave_lines), Decimal("0")),
        leave_hours=sum((line.quantity for line in leave_lines), Decimal("0")),
        has_entries=bool(lines),
    )


# Opus: docstring rationale unratified (ADR 0051).
def _posted_total(timesheet: PostedTimesheet | None) -> Decimal:
    """Sum the hours Xero holds on a timesheet; zero when there is none.

    Summed from the timesheet's own lines rather than read from its
    ``totalHours``: Xero reports that field as 0 for a timesheet it has just
    accepted and fills it in later, so a read straight after a post — which is
    exactly when an operator refreshes — would say the week holds nothing. The
    lines are authoritative immediately, at the cost of one detail call per
    posted employee.
    """
    if timesheet is None:
        return Decimal("0")
    return sum(
        (line.units for line in timesheet_lines(timesheet.timesheet_id)), Decimal("0")
    ).quantize(UNIT_PRECISION)


# Opus: docstring rationale unratified (ADR 0051).
def week_posting_status(week_start_date: date) -> list[StaffWeekPosting]:
    """Report what Xero holds for each staff member's week, beside what we recorded.

    Asked of Xero rather than tracked locally: a local "posted" flag can
    disagree with the payroll system and eventually will (ADR 0007). Its own
    endpoint rather than a field on the weekly overview, so the grid still
    renders when Xero is unreachable.

    The staff list is ``get_displayable_staff`` — the same filter the weekly
    grid uses — rather than "anyone with a non-empty ``xero_user_id``". The
    local filter had no employment window and no id validity check, so it
    answered for people who had left before the week or not yet joined it, and
    those rows could not be matched against a grid that never showed them.

    The leave read costs one Xero call per staff member, and the obvious saving
    — skip it where we recorded no leave and Xero holds no timesheet — is
    rejected. Before a week is posted that describes EVERY staff member, so the
    saving lands exactly where leave booked directly in Xero would be reported
    as "Xero holds 0h leave". The row is already out of sync (``matches``
    requires a timesheet), so the operator is alerted either way; what the skip
    changes is that the figure they are alerted WITH becomes wrong on the
    surface that debits a leave balance. The fan-out is affordable because this
    endpoint is opt-in — the panel's query is disabled until "Check against
    Xero" is pressed — so it costs a call per staff member only when an
    operator has asked this exact question.
    """
    week = _WeekWindow.of(week_start_date)
    timesheets = existing_timesheets_for_week(week)
    recorded = _lines_by_staff(week)
    statuses: list[StaffWeekPosting] = []
    for staff in get_displayable_staff(date_range=(week.start, week.end)):
        timesheet = timesheets.get(str(staff.xero_user_id))
        categories = hour_categories.categorise(list(recorded.get(staff.id, [])))
        statuses.append(
            StaffWeekPosting(
                staff_id=str(staff.id),
                posted=timesheet is not None,
                timesheet_status=None if timesheet is None else str(timesheet.status),
                posted_timesheet_hours=_posted_total(timesheet),
                # Opus: get_displayable_staff's actual_users filter already excludes
                # anyone whose xero_user_id is missing or not UUID-shaped, so
                # this parses rather than guards.
                posted_leave_hours=posted_leave_hours(UUID(str(staff.xero_user_id)), week),
                recorded_timesheet_hours=categories.timesheet,
                recorded_leave_hours=categories.leave,
            )
        )
    return statuses
