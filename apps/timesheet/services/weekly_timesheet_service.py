"""Weekly timesheet overview with the payroll-posting categories.

The week starts on the given Monday and runs 5 or 7 days depending on
``CompanyDefaults.weekend_timesheets_enabled``.

Leave identity, the billable rule and the day-status words all come from
``hour_categories`` — the vocabulary this screen shares with the daily
overview, so a weekly cell means exactly what the daily row for that staff
member and day means (ADR 0039).

Metric failures surface instead of becoming plausible zeroes (ADR 0038):
metrics absent from the wire are not computed as dead work.
"""

import logging
from collections.abc import Iterable
from datetime import date, timedelta
from decimal import Decimal
from typing import TypedDict

from django.utils import timezone

from apps.accounts.models import Staff
from apps.accounts.staff_directory import get_displayable_staff
from apps.core.models import CompanyDefaults
from apps.job.models.costing import CostLine
from apps.timesheet.services import hour_categories
from apps.timesheet.services.daily_timesheet_service import SummaryStatsData

logger = logging.getLogger(__name__)

#: Opus: Money is held to cents; hours keep their own precision.
CENTS = Decimal("0.01")

COMPLETE_WEEK_HOURS = Decimal("35")
PARTIAL_WEEK_HOURS = Decimal("20")


class WeeklyDayData(TypedDict):
    """Data contract for WeeklyDayData."""

    day: str
    hours: Decimal
    billable_hours: Decimal
    scheduled_hours: Decimal
    day_status: str
    leave_type: str | None
    has_leave: bool
    billed_hours: Decimal
    unbilled_hours: Decimal
    overtime_1_5x_hours: Decimal
    overtime_2x_hours: Decimal
    sick_leave_hours: Decimal
    annual_leave_hours: Decimal
    bereavement_leave_hours: Decimal
    other_leave_hours: Decimal
    daily_cost: Decimal
    daily_base_cost: Decimal


class WeeklyStaffData(TypedDict):
    """Data contract for WeeklyStaffData."""

    staff_id: str
    staff_name: str
    weekly_hours: list[WeeklyDayData]
    total_hours: Decimal
    total_billable_hours: Decimal
    total_scheduled_hours: Decimal
    billable_percentage: Decimal
    week_status: str
    total_billed_hours: Decimal
    total_unbilled_hours: Decimal
    total_overtime_hours: Decimal
    total_overtime_1_5x_hours: Decimal
    total_overtime_2x_hours: Decimal
    total_sick_leave_hours: Decimal
    total_annual_leave_hours: Decimal
    total_bereavement_leave_hours: Decimal
    total_other_leave_hours: Decimal
    weekly_cost: Decimal
    weekly_base_cost: Decimal


class WeeklySummaryData(TypedDict):
    """Data contract for WeeklySummaryData."""

    total_hours: Decimal
    staff_count: int
    billable_percentage: Decimal


class JobMetricsData(TypedDict):
    """Data contract for JobMetricsData."""

    total_estimated_profit: float
    total_actual_profit: float
    total_profit: float


class WeeklyNavigationData(TypedDict):
    """Week navigation links added by v1's WeeklyTimesheetAPIView."""

    prev_week_date: str
    next_week_date: str
    current_week_date: str


class WeeklyTimesheetData(TypedDict):
    """Data contract for WeeklyTimesheetData."""

    start_date: str
    end_date: str
    week_days: list[str]
    staff_data: list[WeeklyStaffData]
    weekly_summary: WeeklySummaryData
    job_metrics: JobMetricsData
    summary_stats: SummaryStatsData
    export_mode: str
    is_current_week: bool
    navigation: WeeklyNavigationData
    weekend_enabled: bool
    week_type: str


#: Opus: A payroll week is Monday to Sunday, always — `payroll_push._WeekWindow.of`
#: posts that range whatever this screen displays.
PAYROLL_WEEK_DAYS = 7


def week_days(start_date: date, weekend_enabled: bool) -> list[date]:
    """Return the 5 (Mon-Fri) or 7 (Mon-Sun) days of the configured week shape."""
    day_count = PAYROLL_WEEK_DAYS if weekend_enabled else 5
    return [start_date + timedelta(days=i) for i in range(day_count)]


def _displayed_days(
    payroll_days: list[date],
    grouped: dict[tuple[str, date], list[CostLine]],
    *,
    weekend_enabled: bool,
) -> list[date]:
    """Choose the days this screen shows: never fewer than the days that carry hours.

    Opus: This screen is where a week is reviewed before it is posted, and posting
    always covers Monday to Sunday. Showing Mon-Fri because the weekend flag is
    off therefore hid Saturday and Sunday hours that were transmitted and paid —
    absent from the columns, from `total_hours`, and from the summary. The
    reconciliation could not catch it either: it reads the same Mon-Sun window,
    so posted and recorded agreed and the panel reported a match.

    Opus: The flag still earns its keep — an ordinary week stays five columns wide
    rather than carrying two permanently empty ones — but it can only hide days
    that are empty.
    """
    if weekend_enabled:
        return payroll_days
    weekend_has_hours = any(
        day.weekday() >= 5 and lines for (_staff_id, day), lines in grouped.items()
    )
    return payroll_days if weekend_has_hours else payroll_days[:5]


def _week_status(total_hours: Decimal) -> str:
    """v1's weekly completeness banding for a staff member."""
    if total_hours >= COMPLETE_WEEK_HOURS:
        return "Complete"
    if total_hours >= PARTIAL_WEEK_HOURS:
        return "Partial"
    if total_hours > 0:
        return "Minimal"
    return "Missing"


def _leave_type(cost_lines: list[CostLine]) -> str | None:
    """Name the leave the day was booked against, if any."""
    for line in cost_lines:
        leave = hour_categories.leave_type(line)
        if leave is not None:
            return leave
    return None


def _process_daily_lines(
    staff_member: Staff,
    day: date,
    cost_lines: list[CostLine],
    loading_multiplier: Decimal,
    *,
    weekend_enabled: bool,
) -> WeeklyDayData:
    """Aggregate one staff member's lines for one day into the payroll columns."""
    # Opus: The shared rule, not the roster read directly: this screen now renders
    # weekend days that carry hours, so reading the roster raw would give the
    # same booked Saturday a different status here than on the daily page.
    scheduled_hours = hour_categories.scheduled_hours(
        staff_member, day, weekend_enabled=weekend_enabled
    )
    categories = hour_categories.categorise(cost_lines)
    daily_hours = categories.total
    leave_type = _leave_type(cost_lines)

    # v1 rounds the base cost to cents FIRST and applies the leave loading to the
    # rounded figure, so an operator can reconcile daily_base_cost * loading
    # against daily_cost. Loading the unrounded sum drifts by a cent.
    daily_base_cost = sum((line.total_cost for line in cost_lines), Decimal("0")).quantize(CENTS)

    return {
        "day": day.strftime("%Y-%m-%d"),
        "hours": daily_hours,
        "billable_hours": categories.billable,
        "scheduled_hours": scheduled_hours,
        "day_status": hour_categories.day_status(
            daily_hours, scheduled_hours, has_leave=leave_type is not None
        ),
        "leave_type": leave_type,
        "has_leave": leave_type is not None,
        "billed_hours": categories.billed,
        "unbilled_hours": categories.unbilled,
        "overtime_1_5x_hours": categories.overtime_1_5x,
        "overtime_2x_hours": categories.overtime_2x,
        "sick_leave_hours": categories.sick_leave,
        "annual_leave_hours": categories.annual_leave,
        "bereavement_leave_hours": categories.bereavement_leave,
        "other_leave_hours": categories.other_leave,
        "daily_base_cost": daily_base_cost,
        "daily_cost": (daily_base_cost * loading_multiplier).quantize(CENTS),
    }


def _lines_by_staff_day(days: list[date]) -> dict[tuple[str, date], list[CostLine]]:
    """ONE query for every actual time line in the week, grouped by (staff, day).

    v1's optimisation: ~100 per-staff-per-day queries collapse to one.
    """
    grouped: dict[tuple[str, date], list[CostLine]] = {}
    lines = CostLine.objects.filter(
        cost_set__kind="actual",
        kind="time",
        accounting_date__gte=days[0],
        accounting_date__lte=days[-1],
    ).select_related("cost_set__job", "xero_pay_item")
    for line in lines:
        grouped.setdefault((str(line.staff_id), line.accounting_date), []).append(line)
    return grouped


def _total(values: "Iterable[Decimal]") -> Decimal:
    """Sum a column of Decimals, starting from Decimal rather than int 0.

    Opus: Named rather than inlined because the sums it replaces were the aggregation
    defect: each day's value had been cast to float on the way out, so a week's
    total accumulated binary rounding error and the figure an operator
    reconciled against Xero was not the figure the lines held. The explicit
    zero also keeps an empty week a Decimal instead of the int ``0``.
    """
    return sum(values, Decimal("0"))


def _staff_week(
    staff_member: Staff,
    days: list[date],
    grouped: dict[tuple[str, date], list[CostLine]],
    loading_multiplier: Decimal,
    *,
    weekend_enabled: bool,
) -> WeeklyStaffData:
    """Build one staff member's weekly row from the pre-grouped lines."""
    staff_id = str(staff_member.id)
    daily_rows = [
        _process_daily_lines(
            staff_member,
            day,
            grouped.get((staff_id, day), []),
            loading_multiplier,
            weekend_enabled=weekend_enabled,
        )
        for day in days
    ]

    total_hours = _total(row["hours"] for row in daily_rows)
    total_billable_hours = _total(row["billable_hours"] for row in daily_rows)
    overtime_1_5x = _total(row["overtime_1_5x_hours"] for row in daily_rows)
    overtime_2x = _total(row["overtime_2x_hours"] for row in daily_rows)
    billable_percentage = (
        (total_billable_hours / total_hours * 100) if total_hours > 0 else Decimal("0")
    )

    return {
        "staff_id": staff_id,
        "staff_name": staff_member.get_display_full_name(),
        "weekly_hours": daily_rows,
        "total_hours": total_hours,
        "total_billable_hours": total_billable_hours,
        "total_scheduled_hours": _total(row["scheduled_hours"] for row in daily_rows),
        "billable_percentage": billable_percentage.quantize(Decimal("0.1")),
        "week_status": _week_status(total_hours),
        "total_billed_hours": _total(row["billed_hours"] for row in daily_rows),
        "total_unbilled_hours": _total(row["unbilled_hours"] for row in daily_rows),
        "total_overtime_hours": overtime_1_5x + overtime_2x,
        "total_overtime_1_5x_hours": overtime_1_5x,
        "total_overtime_2x_hours": overtime_2x,
        "total_sick_leave_hours": _total(row["sick_leave_hours"] for row in daily_rows),
        "total_annual_leave_hours": _total(row["annual_leave_hours"] for row in daily_rows),
        "total_bereavement_leave_hours": _total(
            row["bereavement_leave_hours"] for row in daily_rows
        ),
        "total_other_leave_hours": _total(row["other_leave_hours"] for row in daily_rows),
        "weekly_cost": _total(row["daily_cost"] for row in daily_rows).quantize(CENTS),
        "weekly_base_cost": _total(row["daily_base_cost"] for row in daily_rows).quantize(CENTS),
    }


def _weekly_totals(staff_data: list[WeeklyStaffData]) -> WeeklySummaryData:
    """Week totals across all staff."""
    total_hours = sum((row["total_hours"] for row in staff_data), Decimal("0"))
    total_billable_hours = sum((row["total_billable_hours"] for row in staff_data), Decimal("0"))
    billable_percentage = (
        (total_billable_hours / total_hours * 100) if total_hours > 0 else Decimal("0")
    )
    return {
        "total_hours": total_hours.quantize(Decimal("0.1")),
        "staff_count": len(staff_data),
        "billable_percentage": billable_percentage.quantize(Decimal("0.1")),
    }


def _summary_stats(staff_data: list[WeeklyStaffData]) -> SummaryStatsData:
    """Staff counts by weekly completeness."""
    total_staff = len(staff_data)
    complete_staff = len([row for row in staff_data if row["week_status"] == "Complete"])
    completion_rate = (complete_staff / total_staff * 100) if total_staff > 0 else 0.0
    return {
        "total_staff": total_staff,
        "complete_staff": complete_staff,
        "partial_staff": len([row for row in staff_data if row["week_status"] == "Partial"]),
        "missing_staff": len([row for row in staff_data if row["week_status"] == "Missing"]),
        "completion_rate": round(completion_rate, 1),
    }


def _job_metrics(start_date: date, end_date: date) -> JobMetricsData:
    """Estimated vs actual profit across every job worked in the week."""
    cost_lines = CostLine.objects.filter(
        cost_set__kind="actual",
        accounting_date__gte=start_date,
        accounting_date__lte=end_date,
    ).select_related("cost_set__job", "cost_set__job__latest_estimate")

    total_actual_profit = Decimal("0")
    total_estimated_profit = Decimal("0")
    processed_jobs: set[str] = set()

    for line in cost_lines:
        total_actual_profit += line.total_rev - line.total_cost
        job = line.cost_set.job
        if job is None or str(job.id) in processed_jobs:
            continue
        processed_jobs.add(str(job.id))
        estimate = job.latest_estimate
        if estimate is None:
            continue
        summary = estimate.summary
        total_estimated_profit += Decimal(str(summary["rev"])) - Decimal(str(summary["cost"]))

    return {
        "total_estimated_profit": float(total_estimated_profit),
        "total_actual_profit": float(total_actual_profit),
        # v1: total_profit mirrors actual profit.
        "total_profit": float(total_actual_profit),
    }


def _is_current_week(start_date: date) -> bool:
    """Whether the given Monday is this week's Monday."""
    today = timezone.localdate()
    return start_date == today - timedelta(days=today.weekday())


def get_weekly_overview(start_date: date) -> WeeklyTimesheetData:
    """Build the weekly timesheet overview with payroll fields (v1 + the view's extras).

    v1's ``WeeklyTimesheetAPIView`` bolted navigation, ``weekend_enabled`` and
    ``week_type`` onto the service result; they are part of the payload, so
    they are built here rather than in the router (thin routers, house pattern).
    """
    company_defaults = CompanyDefaults.get_solo()
    weekend_enabled = company_defaults.weekend_timesheets_enabled
    loading_multiplier = Decimal("1") + company_defaults.annual_leave_loading / Decimal("100")

    # Opus: Built over the PAYROLL week regardless of the flag, so nothing that will
    # be posted can be missing from what is reviewed.
    payroll_days = week_days(start_date, weekend_enabled=True)
    grouped = _lines_by_staff_day(payroll_days)
    days = _displayed_days(payroll_days, grouped, weekend_enabled=weekend_enabled)
    end_date = days[-1]
    # Opus: The payroll window, not the displayed one: this is the same range
    # `week_posting_status` asks for, so the grid and the reconciliation cannot
    # disagree about who belongs in the week.
    staff_members = get_displayable_staff(date_range=(payroll_days[0], payroll_days[-1]))
    staff_data = [
        _staff_week(
            staff_member, days, grouped, loading_multiplier, weekend_enabled=weekend_enabled
        )
        for staff_member in staff_members
    ]

    return {
        "start_date": start_date.strftime("%Y-%m-%d"),
        "end_date": end_date.strftime("%Y-%m-%d"),
        "week_days": [day.strftime("%Y-%m-%d") for day in days],
        "staff_data": staff_data,
        "weekly_summary": _weekly_totals(staff_data),
        "job_metrics": _job_metrics(start_date, end_date),
        "summary_stats": _summary_stats(staff_data),
        "export_mode": "payroll",
        "is_current_week": _is_current_week(start_date),
        "navigation": {
            "prev_week_date": (start_date - timedelta(days=7)).isoformat(),
            "next_week_date": (start_date + timedelta(days=7)).isoformat(),
            "current_week_date": start_date.isoformat(),
        },
        "weekend_enabled": weekend_enabled,
        "week_type": "7-day" if weekend_enabled else "5-day",
    }
