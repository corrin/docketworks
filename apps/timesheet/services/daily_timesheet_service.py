"""Daily timesheet summary: one day, every displayable staff member.

Ported from v1 ``apps/timesheet/services/daily_timesheet_service.py``. Time
entries are ``job.CostLine`` rows with ``kind="time"`` (the timesheet app is
model-less), so the whole service is read-side aggregation over CostLine.

v1 shaped the response with DRF serializers; v2 builds the wire shape here as
TypedDicts (house pattern: ``apps/job/services/job_service.py``) with the
pydantic schemas in ``apps/timesheet/schemas.py`` as the contract.
"""

import logging
from datetime import date
from decimal import Decimal
from typing import TypedDict

from apps.accounts.models import Staff
from apps.accounts.staff_directory import get_displayable_staff
from apps.core.models import CompanyDefaults
from apps.job.models.costing import CostLine

logger = logging.getLogger(__name__)

# v1 status vocabulary and the CSS class each maps to.
STATUS_CLASSES = {
    "Complete": "success",
    "Partial": "warning",
    "No Entry": "danger",
    "Weekend": "secondary",
    "Weekend Work": "info",
}
PARTIAL_THRESHOLD = Decimal("0.9")
LOW_HOURS_THRESHOLD = Decimal("0.5")
OVERTIME_THRESHOLD = Decimal("1.2")


class JobBreakdownData(TypedDict):
    """v1 JobBreakdownSerializer: one job's share of a staff member's day."""

    job_id: str
    job_number: int
    job_name: str
    company: str
    hours: float
    revenue: float
    cost: float
    is_billable: bool


class StaffDailyData(TypedDict):
    """v1 StaffDailyDataSerializer: one staff member's day."""

    staff_id: str
    staff_name: str
    staff_initials: str
    icon_url: str | None
    scheduled_hours: float
    actual_hours: float
    billable_hours: float
    non_billable_hours: float
    total_revenue: float
    total_cost: float
    status: str
    status_class: str
    billable_percentage: float
    completion_percentage: float
    job_breakdown: list[JobBreakdownData]
    entry_count: int
    alerts: list[str]
    is_weekend: bool
    weekend_enabled: bool


class DailyTotalsData(TypedDict):
    """v1 DailyTotalsSerializer: the day's totals across all staff."""

    total_scheduled_hours: float
    total_actual_hours: float
    total_billable_hours: float
    total_non_billable_hours: float
    total_revenue: float
    total_cost: float
    total_entries: int
    completion_percentage: float
    billable_percentage: float
    missing_hours: float


class SummaryStatsData(TypedDict):
    """v1 SummaryStatsSerializer: staff counts by completion status."""

    total_staff: int
    complete_staff: int
    partial_staff: int
    missing_staff: int
    completion_rate: float


class DailyTimesheetSummaryData(TypedDict):
    """v1 DailyTimesheetSummarySerializer: the whole daily summary payload."""

    date: str
    staff_data: list[StaffDailyData]
    daily_totals: DailyTotalsData
    summary_stats: SummaryStatsData
    weekend_enabled: bool
    is_weekend: bool


def _percentage(part: float, total: float) -> float:
    """Percentage of ``part`` in ``total``, zero-safe (v1)."""
    if total == 0:
        return 0.0
    return (part / total) * 100


def _scheduled_hours(staff: Staff, target_date: date, weekend_enabled: bool) -> Decimal:
    """Scheduled hours for the staff member on the date (0 on a 5-day-week weekend)."""
    if not weekend_enabled and target_date.weekday() >= 5:
        return Decimal("0.0")
    return Decimal(str(staff.get_scheduled_hours(target_date)))


def _determine_status(
    actual_hours: Decimal, scheduled_hours: Decimal, weekend_enabled: bool
) -> str:
    """v1 status ladder: weekend > no entry > partial (<90%) > complete."""
    if scheduled_hours == 0:
        if weekend_enabled and actual_hours > 0:
            return "Weekend Work"
        return "Weekend"
    if actual_hours == 0:
        return "No Entry"
    if actual_hours < scheduled_hours * PARTIAL_THRESHOLD:
        return "Partial"
    if actual_hours >= scheduled_hours:
        return "Complete"
    return "Partial"


def _job_breakdown(cost_lines: list[CostLine]) -> list[JobBreakdownData]:
    """Hours/revenue/cost grouped by job, hours descending (v1).

    Job identity comes from the CostSet relationship, never ``meta.job_id`` —
    the relationship cannot drift from the source Job.
    """
    by_job: dict[str, JobBreakdownData] = {}
    hours_by_job: dict[str, Decimal] = {}
    revenue_by_job: dict[str, Decimal] = {}
    cost_by_job: dict[str, Decimal] = {}

    for line in cost_lines:
        job = line.cost_set.job if line.cost_set else None
        if job is None:
            continue
        job_id = str(job.id)
        if job_id not in by_job:
            by_job[job_id] = {
                "job_id": job_id,
                "job_number": job.job_number,
                "job_name": job.name,
                "company": job.company.name if job.company else "",
                "hours": 0.0,
                "revenue": 0.0,
                "cost": 0.0,
                "is_billable": bool(line.meta.get("is_billable", True)),
            }
            hours_by_job[job_id] = Decimal("0")
            revenue_by_job[job_id] = Decimal("0")
            cost_by_job[job_id] = Decimal("0")
        hours_by_job[job_id] += line.quantity
        revenue_by_job[job_id] += line.total_rev
        cost_by_job[job_id] += line.total_cost

    for job_id, row in by_job.items():
        row["hours"] = float(hours_by_job[job_id])
        row["revenue"] = float(revenue_by_job[job_id])
        row["cost"] = float(cost_by_job[job_id])

    return sorted(by_job.values(), key=lambda row: row["hours"], reverse=True)


def _staff_alerts(
    actual_hours: Decimal, scheduled_hours: Decimal, cost_lines: list[CostLine]
) -> list[str]:
    """Operator-facing warnings about a staff member's day (v1)."""
    alerts: list[str] = []
    if actual_hours == 0 and scheduled_hours > 0:
        alerts.append("No timesheet entries")
    if 0 < actual_hours < scheduled_hours * LOW_HOURS_THRESHOLD:
        alerts.append("Low hours recorded")
    if actual_hours > scheduled_hours * OVERTIME_THRESHOLD:
        alerts.append("Overtime recorded")
    missing_job_entries = [line for line in cost_lines if not (line.cost_set and line.cost_set.job)]
    if missing_job_entries:
        alerts.append(f"{len(missing_job_entries)} entries missing job info")
    return alerts


def get_staff_timesheet_data(
    staff: Staff, target_date: date, weekend_enabled: bool
) -> StaffDailyData:
    """Build one staff member's daily row (v1 ``_get_staff_timesheet_data``)."""
    cost_lines = list(
        CostLine.objects.filter(
            kind="time",
            staff=staff,
            accounting_date=target_date,
        ).select_related("cost_set__job__company")
    )

    total_hours = sum((line.quantity for line in cost_lines), Decimal("0"))
    billable_hours = sum(
        (line.quantity for line in cost_lines if line.meta.get("is_billable", True)),
        Decimal("0"),
    )
    total_revenue = sum((line.total_rev for line in cost_lines), Decimal("0"))
    total_cost = sum((line.total_cost for line in cost_lines), Decimal("0"))
    scheduled_hours = _scheduled_hours(staff, target_date, weekend_enabled)
    status = _determine_status(total_hours, scheduled_hours, weekend_enabled)

    logger.info(
        "Processed timesheet for %s %s: %sh (%d entries)",
        staff.first_name,
        staff.last_name,
        total_hours,
        len(cost_lines),
    )
    return {
        "staff_id": str(staff.id),
        "staff_name": f"{staff.first_name} {staff.last_name}",
        "staff_initials": f"{staff.first_name[:1]}{staff.last_name[:1]}".upper(),
        "icon_url": staff.icon.url if staff.icon else None,
        "scheduled_hours": float(scheduled_hours),
        "actual_hours": float(total_hours),
        "billable_hours": float(billable_hours),
        "non_billable_hours": float(total_hours - billable_hours),
        "total_revenue": float(total_revenue),
        "total_cost": float(total_cost),
        "status": status,
        "status_class": STATUS_CLASSES.get(status, "secondary"),
        "billable_percentage": _percentage(float(billable_hours), float(total_hours)),
        "completion_percentage": _percentage(float(total_hours), float(scheduled_hours)),
        "job_breakdown": _job_breakdown(cost_lines),
        "entry_count": len(cost_lines),
        "alerts": _staff_alerts(total_hours, scheduled_hours, cost_lines),
        # v1 wire parity: the DRF serializer defaulted both flags to False and
        # the view never supplied them (parity ledger — candidate fix, not a
        # silent behaviour change here).
        "is_weekend": False,
        "weekend_enabled": False,
    }


def _staff_daily_rows(target_date: date, weekend_enabled: bool) -> list[StaffDailyData]:
    """Every displayable staff member's row for the date (v1 ``_get_staff_daily_data``).

    Staff with no scheduled hours that day are excluded unless weekend
    timesheets are enabled and the date is a weekend.
    """
    is_weekend = target_date.weekday() >= 5
    rows: list[StaffDailyData] = []
    for staff in get_displayable_staff(target_date=target_date):
        if staff.get_scheduled_hours(target_date) <= 0 and not (weekend_enabled and is_weekend):
            logger.debug(
                "Excluding staff %s - no working hours for %s",
                staff.id,
                target_date.strftime("%A"),
            )
            continue
        rows.append(get_staff_timesheet_data(staff, target_date, weekend_enabled))
    return rows


def _daily_totals(staff_data: list[StaffDailyData]) -> DailyTotalsData:
    """Sum the staff rows into the day's totals (v1)."""
    total_scheduled = sum(row["scheduled_hours"] for row in staff_data)
    total_actual = sum(row["actual_hours"] for row in staff_data)
    total_billable = sum(row["billable_hours"] for row in staff_data)
    return {
        "total_scheduled_hours": total_scheduled,
        "total_actual_hours": total_actual,
        "total_billable_hours": total_billable,
        "total_non_billable_hours": total_actual - total_billable,
        "total_revenue": sum(row["total_revenue"] for row in staff_data),
        "total_cost": sum(row["total_cost"] for row in staff_data),
        "total_entries": sum(row["entry_count"] for row in staff_data),
        "completion_percentage": _percentage(total_actual, total_scheduled),
        "billable_percentage": _percentage(total_billable, total_actual),
        "missing_hours": max(0.0, total_scheduled - total_actual),
    }


def _summary_stats(staff_data: list[StaffDailyData]) -> SummaryStatsData:
    """Staff counts by completion status (v1)."""
    total_staff = len(staff_data)
    complete_staff = len([row for row in staff_data if row["status"] == "Complete"])
    return {
        "total_staff": total_staff,
        "complete_staff": complete_staff,
        "partial_staff": len([row for row in staff_data if row["status"] == "Partial"]),
        "missing_staff": len([row for row in staff_data if row["status"] == "No Entry"]),
        "completion_rate": _percentage(complete_staff, total_staff),
    }


def get_daily_summary(target_date: date) -> DailyTimesheetSummaryData:
    """Build the daily timesheet summary for every displayable staff member (v1)."""
    weekend_enabled = CompanyDefaults.get_solo().weekend_timesheets_enabled
    staff_data = _staff_daily_rows(target_date, weekend_enabled)
    return {
        "date": target_date.isoformat(),
        "staff_data": staff_data,
        "daily_totals": _daily_totals(staff_data),
        "summary_stats": _summary_stats(staff_data),
        # v1 wire parity: see get_staff_timesheet_data.
        "weekend_enabled": False,
        "is_weekend": False,
    }


def get_staff_daily_detail(staff_id: str, target_date: date) -> StaffDailyData | None:
    """One staff member's daily row, or None when they are not in the summary (v1)."""
    summary = get_daily_summary(target_date)
    return next(
        (row for row in summary["staff_data"] if row["staff_id"] == staff_id),
        None,
    )
