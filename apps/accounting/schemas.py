"""Response schemas for the accounting report surface.

Shapes mirror v1's DRF serializers (apps/accounting/serializers/) — the wire
contract, which is narrower than what the services compute (v1's serializers
silently dropped extra keys; ninja schemas do the same by omission). Fields the
v1 serializer dropped (e.g. job-aging ``price_cap``) stay dropped.
"""

from datetime import date

from ninja import Schema


class JobAgingFinancialData(Schema):
    """v1 JobAgingFinancialDataSerializer."""

    estimate_total: float
    quote_total: float
    actual_total: float


class JobAgingTimingData(Schema):
    """v1 JobAgingTimingDataSerializer."""

    created_date: date
    created_days_ago: int
    days_in_current_status: int
    # v1 declared last_activity_date a DateTimeField but the service always
    # supplied a bare date; v2 types what is actually sent.
    last_activity_date: date | None
    last_activity_days_ago: int | None
    last_activity_type: str | None
    last_activity_description: str | None


class JobAgingJobData(Schema):
    """v1 JobAgingJobDataSerializer (price_cap intentionally absent, as in v1)."""

    id: str
    job_number: int
    name: str
    company_name: str
    status: str
    status_display: str
    financial_data: JobAgingFinancialData
    timing_data: JobAgingTimingData


class JobAgingResponse(Schema):
    """v1 JobAgingResponseSerializer."""

    jobs: list[JobAgingJobData]


class WIPJobRowOut(Schema):
    """v1 WIPJobSerializer."""

    job_number: int
    name: str
    company: str
    status: str
    time_cost: float
    time_rev: float
    material_cost: float
    material_rev: float
    adjust_cost: float
    adjust_rev: float
    total_cost: float
    total_rev: float
    invoiced: float
    gross_wip: float
    net_wip: float


class WIPStatusBreakdownOut(Schema):
    """v1 WIPStatusBreakdownSerializer."""

    status: str
    count: int
    net_wip: float


class WIPSummaryOut(Schema):
    """v1 WIPSummarySerializer."""

    job_count: int
    total_gross: float
    total_invoiced: float
    total_net: float
    by_status: list[WIPStatusBreakdownOut]


class WIPResponse(Schema):
    """v1 WIPResponseSerializer."""

    jobs: list[WIPJobRowOut]
    archived_jobs: list[WIPJobRowOut]
    summary: WIPSummaryOut
    report_date: str
    method: str


class RDTICategorySummaryOut(Schema):
    """v1 RDTISpendCategorySummarySerializer.

    rdti_type is a plain string because "unclassified" is a report category,
    not an RDTIType choice — v1 validated against the enum and therefore
    500'd on every call.
    """

    rdti_type: str
    label: str
    hours: float
    cost: float
    revenue: float
    job_count: int


class RDTIJobDetailOut(Schema):
    """v1 RDTISpendJobDetailSerializer."""

    job_id: str
    job_number: int
    job_name: str
    company_name: str
    rdti_type: str
    hours: float
    cost: float
    revenue: float


class RDTITotalsOut(Schema):
    """v1 RDTISpendTotalsSerializer."""

    hours: float
    cost: float
    revenue: float


class RDTISpendResponse(Schema):
    """v1 RDTISpendResponseSerializer."""

    start_date: date
    end_date: date
    summary: list[RDTICategorySummaryOut]
    jobs: list[RDTIJobDetailOut]
    totals: RDTITotalsOut


class StaffJobBreakdownOut(Schema):
    """v1 StaffPerformanceJobBreakdownSerializer."""

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


class StaffMetricsOut(Schema):
    """v1 StaffPerformanceStaffDataSerializer (job_breakdown detail-only)."""

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
    job_breakdown: list[StaffJobBreakdownOut] | None = None


class TeamAveragesOut(Schema):
    """v1 StaffPerformanceTeamAveragesSerializer."""

    billable_percentage: float
    revenue_per_hour: float
    profit_per_hour: float
    jobs_per_person: float
    total_hours: float
    billable_hours: float
    total_revenue: float
    total_profit: float


class PeriodSummaryOut(Schema):
    """v1 StaffPerformancePeriodSummarySerializer."""

    start_date: date
    end_date: date
    total_staff: int
    period_description: str


class StaffPerformanceResponse(Schema):
    """v1 StaffPerformanceResponseSerializer."""

    team_averages: TeamAveragesOut
    staff: list[StaffMetricsOut]
    period_summary: PeriodSummaryOut
