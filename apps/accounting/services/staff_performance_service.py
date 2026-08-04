"""Staff performance report: billable utilisation and per-hour rates.

Ported from v1 ``apps/accounting/services/core.py`` (StaffPerformanceService).
Billable means the line's meta flag is true AND the job is not the shop
company's — shop work never bills. Two v1 quirks kept for parity, recorded in
rewrite-status: total_revenue sums ALL lines (shop included) even though
billable_hours excludes shop work, and the team billable_percentage is the
unweighted mean of per-staff percentages (the timesheet screens compute the
weighted total-over-total instead). One v1 defect is NOT ported: v1's
empty-team branch returned only half the keys its serializer required, so a
period with no recorded hours always 500'd (ledgered).
"""

from datetime import date
from typing import TypedDict
from uuid import UUID

from apps.accounting.services.billable import is_billable_line
from apps.accounts.models import Staff
from apps.accounts.staff_directory import get_displayable_staff
from apps.core.models import CompanyDefaults
from apps.job.models.costing import CostLine


class JobBreakdown(TypedDict):
    """One job's slice of a staff member's period (detail view only)."""

    job_id: str
    job_number: int
    job_name: str
    company_name: str
    billable_hours: float
    non_billable_hours: float
    total_hours: float
    revenue: float
    cost: float
    profit: float
    revenue_per_hour: float


class StaffMetrics(TypedDict, total=False):
    """One staff member's period metrics; job_breakdown only in the detail view."""

    staff_id: str
    name: str
    total_hours: float
    billable_hours: float
    billable_percentage: float
    total_revenue: float
    total_cost: float
    profit: float
    revenue_per_hour: float
    profit_per_hour: float
    jobs_worked: int
    job_breakdown: list[JobBreakdown]


class TeamAverages(TypedDict):
    """Cross-staff averages and totals."""

    billable_percentage: float
    revenue_per_hour: float
    profit_per_hour: float
    jobs_per_person: float
    total_hours: float
    billable_hours: float
    total_revenue: float
    total_profit: float


class PeriodSummary(TypedDict):
    """The reporting window."""

    start_date: str
    end_date: str
    total_staff: int
    period_description: str


class StaffPerformanceData(TypedDict):
    """The whole report body."""

    team_averages: TeamAverages
    staff: list[StaffMetrics]
    period_summary: PeriodSummary


def get_staff_performance_data(
    start_date: date, end_date: date, staff_id: str | None = None
) -> StaffPerformanceData:
    """Per-staff metrics (staff with hours only) plus team averages."""
    cost_lines = CostLine.objects.filter(
        cost_set__kind="actual",
        kind="time",
        accounting_date__gte=start_date,
        accounting_date__lte=end_date,
    ).select_related("cost_set__job__company")

    all_staff = get_displayable_staff(date_range=(start_date, end_date))
    if staff_id:
        all_staff = all_staff.filter(id=staff_id)

    include_job_breakdown = staff_id is not None
    shop_company_id = CompanyDefaults.get_solo().shop_company_id

    lines_by_staff_id: dict[str, list[CostLine]] = {}
    for line in cost_lines:
        if line.staff_id is None:
            continue
        lines_by_staff_id.setdefault(str(line.staff_id), []).append(line)

    staff_data = []
    for staff in all_staff:
        metrics = _staff_metrics(
            staff,
            lines_by_staff_id.get(str(staff.id), []),
            include_job_breakdown,
            shop_company_id,
        )
        # Only staff with recorded hours in the period appear.
        if metrics["total_hours"] > 0:
            staff_data.append(metrics)

    return StaffPerformanceData(
        team_averages=_team_averages(staff_data),
        staff=staff_data,
        period_summary=PeriodSummary(
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
            total_staff=len(staff_data),
            period_description=(
                f"{start_date.strftime('%B %d')} - {end_date.strftime('%B %d, %Y')}"
            ),
        ),
    )


def _staff_metrics(
    staff: Staff,
    cost_lines: list[CostLine],
    include_job_breakdown: bool,
    shop_company_id: UUID | None,
) -> StaffMetrics:
    total_hours = float(sum(line.quantity for line in cost_lines))
    billable_hours = float(
        sum(line.quantity for line in cost_lines if is_billable_line(line, shop_company_id))
    )
    # v1 parity: revenue/cost sum ALL lines, shop work included, even though
    # billable_hours excludes it.
    total_revenue = float(sum(line.total_rev for line in cost_lines))
    total_cost = float(sum(line.total_cost for line in cost_lines))
    profit = total_revenue - total_cost

    metrics = StaffMetrics(
        staff_id=str(staff.id),
        name=staff.get_display_full_name(),
        total_hours=total_hours,
        billable_hours=billable_hours,
        billable_percentage=(billable_hours / total_hours * 100 if total_hours > 0 else 0),
        total_revenue=total_revenue,
        total_cost=total_cost,
        profit=profit,
        revenue_per_hour=total_revenue / total_hours if total_hours > 0 else 0,
        profit_per_hour=profit / total_hours if total_hours > 0 else 0,
        jobs_worked=len({line.cost_set.job.id for line in cost_lines}),
    )
    if include_job_breakdown:
        metrics["job_breakdown"] = _job_breakdown(cost_lines, shop_company_id)
    return metrics


def _job_breakdown(cost_lines: list[CostLine], shop_company_id: UUID | None) -> list[JobBreakdown]:
    job_data: dict[str, JobBreakdown] = {}
    for line in cost_lines:
        job = line.cost_set.job
        row = job_data.setdefault(
            str(job.id),
            JobBreakdown(
                job_id=str(job.id),
                job_number=job.job_number,
                job_name=job.name,
                company_name=job.company.name if job.company else "",
                billable_hours=0.0,
                non_billable_hours=0.0,
                total_hours=0.0,
                revenue=0.0,
                cost=0.0,
                profit=0.0,
                revenue_per_hour=0.0,
            ),
        )
        hours = float(line.quantity)
        if is_billable_line(line, shop_company_id):
            row["billable_hours"] += hours
        else:
            row["non_billable_hours"] += hours
        row["revenue"] += float(line.total_rev)
        row["cost"] += float(line.total_cost)

    for row in job_data.values():
        row["total_hours"] = row["billable_hours"] + row["non_billable_hours"]
        row["profit"] = row["revenue"] - row["cost"]
        row["revenue_per_hour"] = (
            row["revenue"] / row["total_hours"] if row["total_hours"] > 0 else 0
        )
    return list(job_data.values())


def _team_averages(staff_data: list[StaffMetrics]) -> TeamAverages:
    if not staff_data:
        return TeamAverages(
            billable_percentage=0.0,
            revenue_per_hour=0.0,
            profit_per_hour=0.0,
            jobs_per_person=0.0,
            total_hours=0.0,
            billable_hours=0.0,
            total_revenue=0.0,
            total_profit=0.0,
        )

    staff_count = len(staff_data)
    return TeamAverages(
        # Unweighted mean of per-staff percentages (v1 parity; the timesheet
        # screens use weighted total-over-total — recorded divergence).
        billable_percentage=(sum(s["billable_percentage"] for s in staff_data) / staff_count),
        revenue_per_hour=sum(s["revenue_per_hour"] for s in staff_data) / staff_count,
        profit_per_hour=sum(s["profit_per_hour"] for s in staff_data) / staff_count,
        jobs_per_person=sum(s["jobs_worked"] for s in staff_data) / staff_count,
        total_hours=sum(s["total_hours"] for s in staff_data),
        billable_hours=sum(s["billable_hours"] for s in staff_data),
        total_revenue=sum(s["total_revenue"] for s in staff_data),
        total_profit=sum(s["profit"] for s in staff_data),
    )
