"""Weekly timesheet overview with the payroll-posting categories.

The week starts on the given Monday and runs 5 or 7 days depending on
``CompanyDefaults.weekend_timesheets_enabled``.

Two tempting alternatives are deliberately rejected:

- Missing ``meta.is_billable`` means billable, matching every other timesheet
  surface; a local non-billable default would make summaries disagree (ADR 0039).
- Metric failures surface instead of becoming plausible zeroes (ADR 0038).
  Metrics absent from the wire are not computed as dead work.
"""

import logging
from datetime import date, timedelta
from decimal import Decimal
from typing import TypedDict

from django.utils import timezone

from apps.accounts.models import Staff
from apps.accounts.staff_directory import get_displayable_staff
from apps.core.models import CompanyDefaults
from apps.job.models.costing import CostLine
from apps.timesheet.services.daily_timesheet_service import SummaryStatsData

logger = logging.getLogger(__name__)

COMPLETE_WEEK_HOURS = 35.0
PARTIAL_WEEK_HOURS = 20.0
OVERTIME_1_5X = Decimal("1.50")
OVERTIME_2X = Decimal("2.00")
# Leave pay items whose hours are reported separately in the payroll columns.
LEAVE_PAY_ITEM_FIELDS = {
    "Sick Leave": "sick_leave_hours",
    "Annual Leave": "annual_leave_hours",
    "Bereavement Leave": "bereavement_leave_hours",
}


class WeeklyDayData(TypedDict):
    """Data contract for WeeklyDayData."""

    day: str
    hours: float
    billable_hours: float
    scheduled_hours: float
    status: str
    leave_type: str | None
    has_leave: bool
    billed_hours: float
    unbilled_hours: float
    overtime_1_5x_hours: float
    overtime_2x_hours: float
    sick_leave_hours: float
    annual_leave_hours: float
    bereavement_leave_hours: float
    daily_cost: float
    daily_base_cost: float


class WeeklyStaffData(TypedDict):
    """Data contract for WeeklyStaffData."""

    staff_id: str
    name: str
    weekly_hours: list[WeeklyDayData]
    total_hours: float
    total_billable_hours: float
    total_scheduled_hours: float
    billable_percentage: float
    status: str
    total_billed_hours: float
    total_unbilled_hours: float
    total_overtime_hours: float
    total_overtime_1_5x_hours: float
    total_overtime_2x_hours: float
    total_sick_leave_hours: float
    total_annual_leave_hours: float
    total_bereavement_leave_hours: float
    weekly_cost: float
    weekly_base_cost: float


class WeeklySummaryData(TypedDict):
    """Data contract for WeeklySummaryData."""

    total_hours: float
    staff_count: int
    billable_percentage: float


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


def week_days(start_date: date, weekend_enabled: bool) -> list[date]:
    """Return the 5 (Mon-Fri) or 7 (Mon-Sun) days of the configured week shape."""
    day_count = 7 if weekend_enabled else 5
    return [start_date + timedelta(days=i) for i in range(day_count)]


def _is_billable(line: CostLine) -> bool:
    """Whether a time line bills the customer (missing key means billable)."""
    return bool(line.meta.get("is_billable", True))


def _wage_rate_multiplier(line: CostLine) -> Decimal:
    """Read the line's wage multiplier from meta, defaulting to 1x."""
    raw = line.meta.get("wage_rate_multiplier")
    if raw is None:
        return Decimal("1.0")
    return Decimal(str(raw))


def _day_status(daily_hours: float, scheduled_hours: float, has_leave: bool) -> str:
    """v1's single-character day marker (leave / off / short / met)."""
    if has_leave:
        return "Leave"
    if scheduled_hours == 0:
        return "Off"
    if daily_hours == 0:
        return "⚠"
    if daily_hours >= scheduled_hours:
        return "✓"
    return "⚠"


def _staff_status(total_hours: float) -> str:
    """v1's weekly completeness banding for a staff member."""
    if total_hours >= COMPLETE_WEEK_HOURS:
        return "Complete"
    if total_hours >= PARTIAL_WEEK_HOURS:
        return "Partial"
    if total_hours > 0:
        return "Minimal"
    return "Missing"


def _split_work_and_leave(cost_lines: list[CostLine]) -> tuple[list[CostLine], list[CostLine]]:
    """Split a day's lines into work and leave by the job's name."""
    work: list[CostLine] = []
    leave: list[CostLine] = []
    for line in cost_lines:
        job = line.cost_set.job if line.cost_set else None
        if job is not None and "Leave" in job.name:
            leave.append(line)
        else:
            work.append(line)
    return work, leave


def _work_hour_categories(work_lines: list[CostLine]) -> dict[str, Decimal]:
    """Billed/unbilled/overtime hour splits for a day's work lines (v1).

    Lines on a 0x multiplier (unpaid) count towards neither payroll bucket.
    """
    totals = {
        "billed_hours": Decimal("0"),
        "unbilled_hours": Decimal("0"),
        "overtime_1_5x_hours": Decimal("0"),
        "overtime_2x_hours": Decimal("0"),
        "weighted_hours": Decimal("0"),
    }
    for line in work_lines:
        multiplier = _wage_rate_multiplier(line)
        hours = line.quantity
        totals["weighted_hours"] += hours * multiplier
        if multiplier == Decimal("0.0"):
            continue
        if _is_billable(line):
            totals["billed_hours"] += hours
        else:
            totals["unbilled_hours"] += hours
        if multiplier == OVERTIME_1_5X:
            totals["overtime_1_5x_hours"] += hours
        elif multiplier == OVERTIME_2X:
            totals["overtime_2x_hours"] += hours
    return totals


def _leave_hour_categories(leave_lines: list[CostLine]) -> dict[str, Decimal]:
    """Sick/annual/bereavement hour splits for a day's leave lines."""
    totals = {field: Decimal("0") for field in LEAVE_PAY_ITEM_FIELDS.values()}
    totals["weighted_hours"] = Decimal("0")
    for line in leave_lines:
        job = line.cost_set.job if line.cost_set else None
        pay_item = job.default_xero_pay_item if job is not None else None
        if pay_item is None:
            continue
        field = LEAVE_PAY_ITEM_FIELDS.get(pay_item.name)
        if field is None:
            continue
        totals[field] += line.quantity
        totals["weighted_hours"] += line.quantity
    return totals


def _process_daily_lines(
    staff_member: Staff, day: date, cost_lines: list[CostLine], loading_multiplier: Decimal
) -> WeeklyDayData:
    """Aggregate one staff member's lines for one day into the payroll columns."""
    scheduled_hours = staff_member.get_scheduled_hours(day)
    work_lines, leave_lines = _split_work_and_leave(cost_lines)

    daily_hours = sum((line.quantity for line in cost_lines), Decimal("0"))
    billable_hours = sum((line.quantity for line in cost_lines if _is_billable(line)), Decimal("0"))
    leave_job = leave_lines[0].cost_set.job if leave_lines and leave_lines[0].cost_set else None

    work = _work_hour_categories(work_lines)
    leave = _leave_hour_categories(leave_lines)
    # v1 rounds the base cost to cents FIRST and applies the leave loading to the
    # rounded figure, so an operator can reconcile daily_base_cost * loading
    # against daily_cost. Loading the unrounded sum drifts by a cent.
    daily_base_cost = round(float(sum((line.total_cost for line in cost_lines), Decimal("0"))), 2)

    return {
        "day": day.strftime("%Y-%m-%d"),
        "hours": float(daily_hours),
        "billable_hours": float(billable_hours),
        "scheduled_hours": scheduled_hours,
        "status": _day_status(float(daily_hours), scheduled_hours, bool(leave_lines)),
        "leave_type": leave_job.name if leave_job is not None else None,
        "has_leave": bool(leave_lines),
        "billed_hours": float(work["billed_hours"]),
        "unbilled_hours": float(work["unbilled_hours"]),
        "overtime_1_5x_hours": float(work["overtime_1_5x_hours"]),
        "overtime_2x_hours": float(work["overtime_2x_hours"]),
        "sick_leave_hours": float(leave["sick_leave_hours"]),
        "annual_leave_hours": float(leave["annual_leave_hours"]),
        "bereavement_leave_hours": float(leave["bereavement_leave_hours"]),
        "daily_base_cost": daily_base_cost,
        "daily_cost": round(daily_base_cost * float(loading_multiplier), 2),
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
    ).select_related("cost_set__job", "cost_set__job__default_xero_pay_item")
    for line in lines:
        grouped.setdefault((str(line.staff_id), line.accounting_date), []).append(line)
    return grouped


def _staff_week(
    staff_member: Staff,
    days: list[date],
    grouped: dict[tuple[str, date], list[CostLine]],
    loading_multiplier: Decimal,
) -> WeeklyStaffData:
    """Build one staff member's weekly row from the pre-grouped lines."""
    staff_id = str(staff_member.id)
    daily_rows = [
        _process_daily_lines(
            staff_member, day, grouped.get((staff_id, day), []), loading_multiplier
        )
        for day in days
    ]

    total_hours = sum(row["hours"] for row in daily_rows)
    total_billable_hours = sum(row["billable_hours"] for row in daily_rows)
    overtime_1_5x = sum(row["overtime_1_5x_hours"] for row in daily_rows)
    overtime_2x = sum(row["overtime_2x_hours"] for row in daily_rows)
    billable_percentage = (total_billable_hours / total_hours * 100) if total_hours > 0 else 0.0

    return {
        "staff_id": staff_id,
        "name": staff_member.get_display_full_name(),
        "weekly_hours": daily_rows,
        "total_hours": total_hours,
        "total_billable_hours": total_billable_hours,
        "total_scheduled_hours": sum(row["scheduled_hours"] for row in daily_rows),
        "billable_percentage": round(billable_percentage, 1),
        "status": _staff_status(total_hours),
        "total_billed_hours": sum(row["billed_hours"] for row in daily_rows),
        "total_unbilled_hours": sum(row["unbilled_hours"] for row in daily_rows),
        "total_overtime_hours": overtime_1_5x + overtime_2x,
        "total_overtime_1_5x_hours": overtime_1_5x,
        "total_overtime_2x_hours": overtime_2x,
        "total_sick_leave_hours": sum(row["sick_leave_hours"] for row in daily_rows),
        "total_annual_leave_hours": sum(row["annual_leave_hours"] for row in daily_rows),
        "total_bereavement_leave_hours": sum(row["bereavement_leave_hours"] for row in daily_rows),
        "weekly_cost": round(sum(row["daily_cost"] for row in daily_rows), 2),
        "weekly_base_cost": round(sum(row["daily_base_cost"] for row in daily_rows), 2),
    }


def _weekly_totals(staff_data: list[WeeklyStaffData]) -> WeeklySummaryData:
    """Week totals across all staff."""
    total_hours = sum(row["total_hours"] for row in staff_data)
    total_billable_hours = sum(row["total_billable_hours"] for row in staff_data)
    billable_percentage = (total_billable_hours / total_hours * 100) if total_hours > 0 else 0.0
    return {
        "total_hours": round(total_hours, 1),
        "staff_count": len(staff_data),
        "billable_percentage": round(billable_percentage, 1),
    }


def _summary_stats(staff_data: list[WeeklyStaffData]) -> SummaryStatsData:
    """Staff counts by weekly completeness."""
    total_staff = len(staff_data)
    complete_staff = len([row for row in staff_data if row["status"] == "Complete"])
    completion_rate = (complete_staff / total_staff * 100) if total_staff > 0 else 0.0
    return {
        "total_staff": total_staff,
        "complete_staff": complete_staff,
        "partial_staff": len([row for row in staff_data if row["status"] == "Partial"]),
        "missing_staff": len([row for row in staff_data if row["status"] == "Missing"]),
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

    days = week_days(start_date, weekend_enabled)
    end_date = days[-1]
    grouped = _lines_by_staff_day(days)
    staff_members = get_displayable_staff(date_range=(days[0], days[-1]))
    staff_data = [
        _staff_week(staff_member, days, grouped, loading_multiplier)
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
