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


class KPIProfitBreakdownOut(Schema):
    """v1 KPIProfitBreakdownSerializer."""

    labor_profit: float
    material_profit: float
    adjustment_profit: float


class KPIJobBreakdownOut(Schema):
    """v1 KPIJobBreakdownSerializer."""

    job_id: str
    job_number: str
    job_name: str
    company_name: str
    billable_hours: float
    revenue: float
    cost: float
    profit: float
    labour_profit: float
    material_profit: float
    adjustment_profit: float


class KPIDetailsOut(Schema):
    """v1 KPIDetailsSerializer."""

    time_revenue: float
    material_revenue: float
    adjustment_revenue: float
    total_revenue: float
    staff_cost: float
    material_cost: float
    adjustment_cost: float
    total_cost: float
    profit_breakdown: KPIProfitBreakdownOut
    job_breakdown: list[KPIJobBreakdownOut]


class KPIDayDataOut(Schema):
    """v1 KPIDayDataSerializer (holiday_name only on holidays)."""

    date: date
    day: int
    holiday: bool
    holiday_name: str | None = None
    billable_hours: float
    total_hours: float
    shop_hours: float
    shop_percentage: float
    gross_profit: float
    color: str
    gp_target_achievement: float
    details: KPIDetailsOut


class KPIMonthlyTotalsOut(Schema):
    """v1 KPIMonthlyTotalsSerializer."""

    billable_hours: float
    total_hours: float
    shop_hours: float
    gross_profit: float
    days_green: int
    days_amber: int
    days_red: int
    labour_green_days: int
    labour_amber_days: int
    labour_red_days: int
    profit_green_days: int
    profit_amber_days: int
    profit_red_days: int
    working_days: int
    elapsed_workdays: int
    active_workdays: int
    remaining_workdays: int
    time_revenue: float
    material_revenue: float
    adjustment_revenue: float
    staff_cost: float
    material_cost: float
    adjustment_cost: float
    material_profit: float
    adjustment_profit: float
    total_revenue: float
    total_cost: float
    elapsed_target: float
    net_profit: float
    billable_percentage: float
    shop_percentage: float
    avg_daily_gp: float
    avg_daily_gp_so_far: float
    avg_billable_hours_so_far: float
    color_hours: str
    color_gp: str
    color_shop: str


class KPIThresholdsOut(Schema):
    """v1 KPIThresholdsSerializer."""

    kpi_daily_billable_hours_green: float
    kpi_daily_billable_hours_amber: float
    kpi_daily_gp_target: float
    kpi_daily_shop_hours_percentage: float
    kpi_daily_gp_green: float
    kpi_daily_gp_amber: float


class KPICalendarResponse(Schema):
    """v1 KPICalendarDataSerializer."""

    calendar_data: dict[str, KPIDayDataOut]
    monthly_totals: KPIMonthlyTotalsOut
    thresholds: KPIThresholdsOut
    year: int
    month: int


class ForecastMonthOut(Schema):
    """v1 sales_forecast_list inline schema."""

    month: str
    month_label: str
    xero_sales: float
    jm_sales: float
    variance: float
    variance_pct: float


class SalesForecastResponse(Schema):
    """v1 sales_forecast_list response."""

    months: list[ForecastMonthOut]


class ForecastComparisonRowOut(Schema):
    """v1 sales_forecast_month_detail row schema."""

    date: str | None
    company_name: str
    job_number: int | None
    job_name: str | None
    invoice_numbers: str | None
    total_invoiced: float
    job_revenue: float
    variance: float
    job_id: str | None
    job_start_date: str | None
    total_xero_all_time: float | None
    total_jm_all_time: float | None
    variance_all_time: float | None
    note: str | None


class SalesForecastMonthDetailResponse(Schema):
    """v1 sales_forecast_month_detail response."""

    month: str
    month_label: str
    rows: list[ForecastComparisonRowOut]
