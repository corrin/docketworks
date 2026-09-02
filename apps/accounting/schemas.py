"""Published response contracts for the accounting report surface.

These schemas are intentionally narrower than some internal service results;
fields absent from the public contract remain internal.
"""

from datetime import date
from uuid import UUID

from ninja import Schema

# Opus: the wire type is imported from the service that produces it, rather
# than restated here, so the categories a cell can report and the categories
# the ladder can return are one definition. types.py is not the home for it —
# that module is scoped to the provider abstraction (ADR 0012).
from apps.accounting.services.kpi_service import DayCategory, DayColor
from apps.accounting.types import PayrollRowStatus, PayrollXeroSource
from apps.core.schemas import ResponseSchema


class JobAgingFinancialData(Schema):
    """Wire contract for JobAgingFinancialData."""

    estimate_total: float
    quote_total: float
    actual_total: float


class JobAgingTimingData(Schema):
    """Wire contract for JobAgingTimingData."""

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
    """Wire contract for JobAgingJobData."""

    id: str
    job_number: int
    name: str
    company_name: str
    status: str
    status_display: str
    financial_data: JobAgingFinancialData
    timing_data: JobAgingTimingData


class JobAgingResponse(Schema):
    """Wire contract for JobAgingResponse."""

    jobs: list[JobAgingJobData]


class WIPJobRowOut(Schema):
    """Wire contract for WIPJobRowOut."""

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
    """Wire contract for WIPStatusBreakdownOut."""

    status: str
    count: int
    net_wip: float


class WIPSummaryOut(Schema):
    """Wire contract for WIPSummaryOut."""

    job_count: int
    total_gross: float
    total_invoiced: float
    total_net: float
    by_status: list[WIPStatusBreakdownOut]


class WIPResponse(Schema):
    """Wire contract for WIPResponse."""

    jobs: list[WIPJobRowOut]
    archived_jobs: list[WIPJobRowOut]
    summary: WIPSummaryOut
    report_date: str
    method: str


class RDTICategorySummaryOut(Schema):
    """RDTI category summary contract.

    rdti_type is a plain string because "unclassified" is a report category,
    not an RDTIType choice; enum validation would reject a valid report row.
    """

    rdti_type: str
    label: str
    hours: float
    cost: float
    revenue: float
    job_count: int


class RDTIJobDetailOut(Schema):
    """Wire contract for RDTIJobDetailOut."""

    job_id: str
    job_number: int
    job_name: str
    company_name: str
    rdti_type: str
    hours: float
    cost: float
    revenue: float


class RDTITotalsOut(Schema):
    """Wire contract for RDTITotalsOut."""

    hours: float
    cost: float
    revenue: float


class RDTISpendResponse(Schema):
    """Wire contract for RDTISpendResponse."""

    start_date: date
    end_date: date
    summary: list[RDTICategorySummaryOut]
    jobs: list[RDTIJobDetailOut]
    totals: RDTITotalsOut


class StaffJobBreakdownOut(Schema):
    """Wire contract for StaffJobBreakdownOut."""

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


class StaffMetricsOut(ResponseSchema):
    """Wire contract for StaffMetricsOut."""

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
    """Wire contract for TeamAveragesOut."""

    billable_percentage: float
    revenue_per_hour: float
    profit_per_hour: float
    jobs_per_person: float
    total_hours: float
    billable_hours: float
    total_revenue: float
    total_profit: float


class PeriodSummaryOut(Schema):
    """Wire contract for PeriodSummaryOut."""

    start_date: date
    end_date: date
    total_staff: int
    period_description: str


class StaffPerformanceResponse(Schema):
    """Wire contract for StaffPerformanceResponse."""

    team_averages: TeamAveragesOut
    staff: list[StaffMetricsOut]
    period_summary: PeriodSummaryOut


class KPIProfitBreakdownOut(Schema):
    """Wire contract for KPIProfitBreakdownOut."""

    labour_profit: float
    material_profit: float
    adjustment_profit: float


class KPIJobBreakdownOut(Schema):
    """Wire contract for KPIJobBreakdownOut."""

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
    """Wire contract for KPIDetailsOut."""

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


class KPIDayDataOut(ResponseSchema):
    """Wire contract for KPIDayDataOut."""

    date: date
    day: int
    holiday: bool
    holiday_name: str | None = None
    billable_hours: float
    total_hours: float
    shop_hours: float
    shop_percentage: float
    gross_profit: float
    # "weekend" is a category, not a missing value: an ungraded day is not a
    # day whose grade went astray (owner ruling, 2026-09-01). The achievement
    # IS null there — a weekend is owed no target, so the percentage has no
    # denominator, which is a real absence rather than a fake one.
    color_hours: DayCategory
    color_gp: DayCategory
    gp_target_achievement: float | None
    details: KPIDetailsOut


class KPIMonthlyTotalsOut(Schema):
    """Wire contract for KPIMonthlyTotalsOut."""

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
    weekdays: int
    elapsed_weekdays: int
    active_days: int
    remaining_workdays: int
    remaining_weekdays: int
    time_revenue: float
    material_revenue: float
    adjustment_revenue: float
    staff_cost: float
    material_cost: float
    adjustment_cost: float
    labour_profit: float
    material_profit: float
    adjustment_profit: float
    total_revenue: float
    total_cost: float
    elapsed_target: float
    net_profit: float
    billable_percentage: float
    shop_percentage: float
    avg_weekday_gp: float
    avg_active_day_gp: float
    avg_active_day_billable_hours: float
    # The month is always graded, so these are the three-rung ladder rather
    # than the day's four categories — a month is never "weekend".
    color_hours: DayColor
    color_gp: DayColor
    color_shop: DayColor


class KPIThresholdsOut(Schema):
    """Wire contract for KPIThresholdsOut."""

    kpi_daily_billable_hours_green: float
    kpi_daily_billable_hours_amber: float
    kpi_daily_gp_target: float
    kpi_daily_shop_hours_percentage: float
    kpi_daily_gp_green: float
    kpi_daily_gp_amber: float


class KPICalendarResponse(Schema):
    """Wire contract for KPICalendarResponse."""

    calendar_data: dict[str, KPIDayDataOut]
    monthly_totals: KPIMonthlyTotalsOut
    thresholds: KPIThresholdsOut
    year: int
    month: int
    weekend_enabled: bool


class ForecastMonthOut(Schema):
    """Wire contract for ForecastMonthOut."""

    month: str
    month_label: str
    xero_sales: float
    jm_sales: float
    variance: float
    variance_pct: float


class SalesForecastResponse(Schema):
    """Wire contract for SalesForecastResponse."""

    months: list[ForecastMonthOut]


class ForecastComparisonRowOut(Schema):
    """Wire contract for ForecastComparisonRowOut."""

    date: str | None
    company_name: str
    job_number: int | None
    job_name: str | None
    invoice_numbers: str | None
    total_invoiced: float
    job_revenue: float
    variance: float
    job_id: UUID | None
    job_start_date: str | None
    total_xero_all_time: float | None
    total_jm_all_time: float | None
    variance_all_time: float | None
    note: str | None


class SalesForecastMonthDetailResponse(Schema):
    """Wire contract for SalesForecastMonthDetailResponse."""

    month: str
    month_label: str
    rows: list[ForecastComparisonRowOut]


class PipelinePeriodOut(Schema):
    """Wire contract for PipelinePeriodOut."""

    start_date: date
    end_date: date
    rolling_window_weeks: int
    trend_weeks: int
    daily_approved_hours_target: float


class PipelineSizeBucketOut(Schema):
    """Wire contract for PipelineSizeBucketOut."""

    count: int
    hours: float
    hours_per_working_day: float | None
    share_of_hours: float | None


class PipelineFunnelPathOut(Schema):
    """Wire contract for PipelineFunnelPathOut."""

    count: int
    hours: float
    hours_per_working_day: float | None


class PipelineSizeBucketsOut(Schema):
    """Fixed small, medium, and large size buckets."""

    small: PipelineSizeBucketOut
    medium: PipelineSizeBucketOut
    large: PipelineSizeBucketOut


class PipelineFunnelPathsOut(Schema):
    """Fixed instant and estimating funnel paths."""

    instant: PipelineFunnelPathOut
    estimating: PipelineFunnelPathOut


class PipelineScoreboardOut(Schema):
    """Wire contract for PipelineScoreboardOut."""

    approved_hours_total: float
    approved_hours_per_working_day: float | None
    approved_jobs_count: int
    direct_hours: float
    direct_jobs_count: int
    working_days: int
    target_hours_for_period: float
    pace_vs_target: float | None
    by_size_bucket: PipelineSizeBucketsOut
    by_funnel_path: PipelineFunnelPathsOut


class PipelineStageJobOut(Schema):
    """Wire contract for PipelineStageJobOut."""

    id: str
    job_number: int
    name: str
    company_name: str
    hours: float
    value: float
    days_in_stage: int


class PipelineStageOut(Schema):
    """Wire contract for PipelineStageOut."""

    count: int
    hours_total: float
    value_total: float
    avg_days_in_stage: float
    jobs: list[PipelineStageJobOut]


class PipelineSnapshotOut(Schema):
    """Wire contract for PipelineSnapshotOut."""

    as_of: date
    draft: PipelineStageOut
    awaiting_approval: PipelineStageOut


class PipelineVelocityLegOut(Schema):
    """Wire contract for PipelineVelocityLegOut."""

    median_days: float | None
    p80_days: float | None
    sample_size: int


class PipelineVelocityOut(Schema):
    """Wire contract for PipelineVelocityOut."""

    draft_to_quote_sent: PipelineVelocityLegOut
    quote_sent_to_resolved: PipelineVelocityLegOut
    created_to_approved: PipelineVelocityLegOut


class PipelineFunnelBucketOut(Schema):
    """Wire contract for PipelineFunnelBucketOut."""

    count: int
    hours: float


class PipelineFunnelOut(Schema):
    """Wire contract for PipelineFunnelOut."""

    accepted: PipelineFunnelBucketOut
    rejected: PipelineFunnelBucketOut
    waiting: PipelineFunnelBucketOut
    direct: PipelineFunnelBucketOut
    still_draft: PipelineFunnelBucketOut


class PipelineTrendWeekOut(Schema):
    """Wire contract for PipelineTrendWeekOut."""

    week_start: date
    week_end: date
    approved_hours: float
    approved_hours_per_working_day: float
    acceptance_rate_by_hours: float | None
    pipeline_hours_at_week_end: float
    median_velocity_days: float | None
    working_days: int


class PipelineRollingAverageOut(Schema):
    """Wire contract for PipelineRollingAverageOut."""

    week_start: date
    rolling_avg_approved_hours: float


class PipelineTrendOut(Schema):
    """Wire contract for PipelineTrendOut."""

    weeks: list[PipelineTrendWeekOut]
    rolling_average: list[PipelineRollingAverageOut]


class PipelineWarningJobOut(Schema):
    """Wire contract for PipelineWarningJobOut."""

    id: str
    job_number: int | None
    name: str


class PipelineWarningOut(Schema):
    """Wire contract for PipelineWarningOut."""

    code: str
    section: str
    count: int
    sample_jobs: list[PipelineWarningJobOut]


class SalesPipelineResponse(Schema):
    """Wire contract for SalesPipelineResponse."""

    period: PipelinePeriodOut
    scoreboard: PipelineScoreboardOut
    pipeline_snapshot: PipelineSnapshotOut
    velocity: PipelineVelocityOut
    conversion_funnel: PipelineFunnelOut
    trend: PipelineTrendOut
    warnings: list[PipelineWarningOut]


class PayrollStaffWeekRowOut(Schema):
    """Wire contract for PayrollStaffWeekRowOut."""

    #: The reconciliation join identity. Rows, summaries and heatmap columns
    #: key on this; ``name`` is display only — two staff can share one.
    key: str
    name: str
    xero_hours: float
    xero_timesheet_hours: float
    xero_leave_hours: float
    xero_gross: float
    xero_rate: float
    jm_hours: float
    jm_cost: float
    jm_rate: float
    jm_base_pay: float
    pay_diff: float
    hours_diff: float
    cost_diff: float
    hours_cost_impact: float
    rate_cost_impact: float
    status: PayrollRowStatus


class PayrollWeekTotalsOut(Schema):
    """Wire contract for PayrollWeekTotalsOut."""

    xero_gross: float
    jm_cost: float
    diff: float
    xero_hours: float
    jm_hours: float
    #: Opus: Both wage bases travel, so the page's toggle stays presentation. It
    #: was re-summing the base column in the browser because only the loaded
    #: total was sent — a business value computed twice (ADR 0020).
    jm_base_pay: float
    pay_diff: float


class PayrollWeekOut(Schema):
    """Wire contract for PayrollWeekOut."""

    week_start: date
    xero_period_start: date | None
    xero_period_end: date | None
    payment_date: date | None
    totals: PayrollWeekTotalsOut
    mismatch_count: int
    staff: list[PayrollStaffWeekRowOut]


class PayrollWeekReconciliationResponse(Schema):
    """One payroll week reconciled live against the provider."""

    week: PayrollWeekOut
    #: ``live_run`` when the provider's own figures were read from the week's
    #: pay run; ``no_pay_run`` when it has computed nothing to compare against,
    #: which makes every difference an artefact rather than a finding.
    xero_source: PayrollXeroSource
    #: How many people the provider is paying hours we never posted — the
    #: page's headline, counted where the status taxonomy lives.
    unposted_count: int


class PayrollStaffSummaryOut(Schema):
    """Wire contract for PayrollStaffSummaryOut."""

    key: str
    name: str
    xero_hours: float
    xero_gross: float
    jm_hours: float
    jm_cost: float
    hours_diff: float
    cost_diff: float
    hours_cost_impact: float
    rate_cost_impact: float
    weeks_present: int
    weeks_with_mismatch: int


class PayrollHeatmapColumnOut(Schema):
    """One staff column: the join key and the display name."""

    key: str
    name: str


class PayrollHeatmapRowOut(Schema):
    """Wire contract for PayrollHeatmapRowOut. Cells are keyed by staff key."""

    week_start: date
    cells: dict[str, float | None]


class PayrollHeatmapOut(Schema):
    """Wire contract for PayrollHeatmapOut."""

    columns: list[PayrollHeatmapColumnOut]
    rows: list[PayrollHeatmapRowOut]


class PayrollGrandTotalsOut(Schema):
    """Wire contract for PayrollGrandTotalsOut."""

    xero_gross: float
    jm_cost: float
    diff: float
    diff_pct: float


class PayrollReconciliationResponse(Schema):
    """Wire contract for PayrollReconciliationResponse."""

    weeks: list[PayrollWeekOut]
    staff_summaries: list[PayrollStaffSummaryOut]
    heatmap: PayrollHeatmapOut
    grand_totals: PayrollGrandTotalsOut


class PayrollDateRangeResponse(Schema):
    """Wire contract for PayrollDateRangeResponse."""

    aligned_start: date
    aligned_end: date
