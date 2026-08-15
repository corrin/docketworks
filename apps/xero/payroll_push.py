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

import logging
import time
from collections import defaultdict
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
)
from apps.accounts.models import Staff
from apps.core.errors import AppErrorContext, persist_app_error
from apps.core.models import CompanyDefaults
from apps.job.models.costing import CostLine
from apps.xero.auth import get_api_client, get_tenant_id
from apps.xero.helpers import as_date
from apps.xero.models import XeroPayRun
from apps.xero.payroll_leave import reconcile_leave_for_staff_week
from apps.xero.payroll_setup import get_payroll_calendars
from apps.xero.payroll_sync import get_pay_runs_for_sync
from apps.xero.transforms import transform_pay_run

if TYPE_CHECKING:
    from apps.xero.models import XeroPayItem

logger = logging.getLogger(__name__)

# Xero's payroll endpoints rate-limit hard, and a posting run makes several
# mutating calls per employee. v1 measured 3s as the interval that survives a
# full staff list without throttling.
SLEEP_SECONDS = 3
# Xero pays the whole period end + 3 days (the Wednesday after a Sunday end).
PAYMENT_OFFSET_DAYS = 3


@dataclass(frozen=True)
class _WeekWindow:
    """The payroll week being posted."""

    start: date
    end: date

    @classmethod
    def of(cls, week_start_date: date) -> "_WeekWindow":
        """Build the Monday-to-Sunday window, refusing any other start day."""
        if week_start_date.weekday() != 0:
            raise ValueError("week_start_date must be a Monday")
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


def _split_by_api(lines: Sequence[CostLine]) -> tuple[list[CostLine], list[CostLine]]:
    """Split lines into (leave-API lines, timesheet-API lines) by their pay item."""
    leave_lines: list[CostLine] = []
    timesheet_lines: list[CostLine] = []
    for line in lines:
        if _pay_item(line).uses_leave_api:
            leave_lines.append(line)
        else:
            timesheet_lines.append(line)
    return leave_lines, timesheet_lines


def _timesheet_line_payloads(lines: Sequence[CostLine]) -> list[dict[str, Any]]:
    """Aggregate lines into one timesheet line per (date, earnings rate)."""
    totals: defaultdict[tuple[date, str], float] = defaultdict(float)
    for line in lines:
        totals[(line.accounting_date, str(_pay_item(line).xero_id))] += float(line.quantity)
    return [
        {"date": entry_date, "earnings_rate_id": rate_id, "number_of_units": units}
        for (entry_date, rate_id), units in totals.items()
    ]


def _lines_match(existing_lines: Sequence[Any], new_lines: Sequence[dict[str, Any]]) -> bool:
    """Whether Xero already holds exactly these lines, to 2dp.

    Comparing before writing turns a re-post of unchanged hours into a no-op,
    which matters because the alternative is delete-and-recreate.
    """
    if len(existing_lines) != len(new_lines):
        return False
    existing = {
        (as_date(line.date), str(line.earnings_rate_id), round(float(line.number_of_units), 2))
        for line in existing_lines
    }
    incoming = {
        (line["date"], line["earnings_rate_id"], round(line["number_of_units"], 2))
        for line in new_lines
    }
    return existing == incoming


def post_timesheet(
    employee_id: UUID,
    week: _WeekWindow,
    line_payloads: Sequence[dict[str, Any]],
    existing_timesheet: Any | None,
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

    if (
        existing_timesheet is not None
        and existing_timesheet.timesheet_lines
        and _lines_match(existing_timesheet.timesheet_lines, line_payloads)
    ):
        logger.info(
            "Timesheet %s already matches the hours to post; leaving it alone",
            existing_timesheet.timesheet_id,
        )
        return existing_timesheet

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
                    date=payload["date"],
                    earnings_rate_id=payload["earnings_rate_id"],
                    number_of_units=payload["number_of_units"],
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


def _delete_timesheet(api: PayrollNzApi, tenant_id: str, existing: Any) -> None:
    """Clear an existing timesheet, reverting it from Approved first if needed."""
    timesheet_id = str(existing.timesheet_id)
    if existing.status == "Approved":
        api.revert_timesheet(xero_tenant_id=tenant_id, timesheet_id=timesheet_id)
        time.sleep(SLEEP_SECONDS)
    elif existing.status != "Draft":
        # Paid is the case that matters: the money has left, so silently
        # replacing the record would hide a discrepancy rather than fix one.
        raise ValueError(
            f"Timesheet {timesheet_id} is {existing.status!r} and cannot be modified — "
            "it has already been paid. Correct it in Xero."
        )
    api.delete_timesheet(xero_tenant_id=tenant_id, timesheet_id=timesheet_id)
    time.sleep(SLEEP_SECONDS)


def existing_timesheets_for_week(week: _WeekWindow) -> dict[str, Any]:
    """Every timesheet Xero already holds for the week, keyed by employee id.

    One call for the whole batch; the per-employee alternative multiplied the
    posting run's API calls by the size of the staff list.
    """
    response = _payroll_api().get_timesheets(
        xero_tenant_id=_tenant(), start_date=week.start, end_date=week.end
    )
    if not response or not response.timesheets:
        return {}
    return {
        str(timesheet.employee_id): timesheet
        for timesheet in response.timesheets
        if as_date(timesheet.start_date) == week.start
    }


# --- Pay runs ------------------------------------------------------------


def _calendar_id() -> UUID:
    """Return the configured payroll calendar, refusing an unconfigured install."""
    calendar_id = CompanyDefaults.get_solo().xero_payroll_calendar_id
    if not calendar_id:
        raise ValueError(
            "xero_payroll_calendar_id is not configured. Run 'python manage.py xero --setup' first."
        )
    return calendar_id


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
        # Xero creates the calendar's next unprocessed period regardless of the
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

    mirrored, _ = transform_pay_run(created, str(created.pay_run_id))
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
        XeroPayRun.objects.filter(payroll_calendar_id=calendar_id, pay_run_status="Draft")
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


def refresh_pay_runs() -> PayRunSyncResult:
    """Re-sync the local pay-run mirror from Xero.

    The operator's recovery path after posting or deleting a run inside Xero,
    so it reports what actually moved rather than a bare success. Orphans are
    dropped: Xero is master for pay runs, and a run deleted there must not
    keep blocking the one-draft rule locally.
    """
    fetched = get_pay_runs_for_sync().pay_runs
    live_ids = {str(pay_run.pay_run_id) for pay_run in fetched}
    XeroPayRun.objects.exclude(xero_id__in=live_ids).delete()

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
    joined = staff.date_joined.date() if staff.date_joined else None
    if joined is not None and joined > week.end:
        return False
    return not (staff.date_left is not None and staff.date_left < week.start)


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

    # Leave first, and before the pay run exists: Xero locks leave changes once
    # the employee is in a draft pay run (KAN-326).
    for staff_id in staff_ids:
        staff = staff_by_id.get(staff_id)
        if staff is None or not staff.xero_user_id or not _staff_in_week(staff, week):
            continue
        leave_lines, _ = _split_by_api(lines_by_staff.get(staff_id, []))
        reconcile_leave_for_staff_week(UUID(str(staff.xero_user_id)), leave_lines, week)

    ensure_pay_run_for_week(week.start)
    existing = existing_timesheets_for_week(week)

    for staff_id in staff_ids:
        staff = staff_by_id.get(staff_id)
        if staff is None:
            raise ValueError(f"Staff member {staff_id} not found")
        yield _post_one_staff_week(staff, lines_by_staff.get(staff_id, []), week, existing)


def _lines_by_staff(week: _WeekWindow, staff_ids: Sequence[UUID]) -> dict[UUID, list[CostLine]]:
    """One query for the whole batch's time lines, grouped by staff member."""
    grouped: defaultdict[UUID, list[CostLine]] = defaultdict(list)
    for line in _week_time_lines(week, staff_ids):
        if line.staff_id is None:
            # The query filters on staff_id, so this cannot happen; naming it
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
        return StaffWeekPostResult(
            staff_id=str(staff.id),
            staff_name=staff.get_display_full_name(),
            success=False,
            has_entries=bool(lines),
            error=(
                f"{staff.get_display_full_name()} is not linked to a Xero employee. "
                "Ask an administrator to link them, then post again."
            ),
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
    except Exception as exc:  # noqa: BLE001 -- one staff member's failure becomes their own result rather than stranding the rest of the batch; it is persisted and reported, never swallowed
        persist_app_error(
            exc,
            AppErrorContext(
                app="xero",
                function="post_payroll_week",
                additional_context={
                    "staff_id": str(staff.id),
                    "week_start_date": week.start.isoformat(),
                },
            ),
        )
        return StaffWeekPostResult(
            staff_id=str(staff.id),
            staff_name=staff.get_display_full_name(),
            success=False,
            has_entries=bool(lines),
            error=str(exc),
        )

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


def week_posting_status(week_start_date: date) -> list[StaffWeekPosting]:
    """Report what Xero currently holds for each staff member's week.

    Asked of Xero rather than tracked locally: a local "posted" flag can
    disagree with the payroll system and eventually will (ADR 0007). Its own
    endpoint rather than a field on the weekly overview, so the grid still
    renders when Xero is unreachable.
    """
    week = _WeekWindow.of(week_start_date)
    timesheets = existing_timesheets_for_week(week)
    statuses: list[StaffWeekPosting] = []
    for staff in Staff.objects.exclude(xero_user_id__isnull=True).exclude(xero_user_id=""):
        timesheet = timesheets.get(str(staff.xero_user_id))
        statuses.append(
            StaffWeekPosting(
                staff_id=str(staff.id),
                posted=timesheet is not None,
                timesheet_status=None if timesheet is None else str(timesheet.status),
                posted_hours=Decimal("0")
                if timesheet is None
                else sum(
                    (
                        Decimal(str(line.number_of_units))
                        for line in timesheet.timesheet_lines or []
                    ),
                    Decimal("0"),
                ),
            )
        )
    return statuses
