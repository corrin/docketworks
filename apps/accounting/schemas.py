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


class PipelinePeriodOut(Schema):
    """v1 SalesPipelinePeriodSerializer."""

    start_date: date
    end_date: date
    rolling_window_weeks: int
    trend_weeks: int
    daily_approved_hours_target: float


class PipelineSizeBucketOut(Schema):
    """v1 scoreboard by_size_bucket entry."""

    count: int
    hours: float
    hours_per_working_day: float | None
    share_of_hours: float | None


class PipelineFunnelPathOut(Schema):
    """v1 scoreboard by_funnel_path entry."""

    count: int
    hours: float
    hours_per_working_day: float | None


class PipelineSizeBucketsOut(Schema):
    """Fixed small/medium/large keys (v1 SIZE_BUCKETS)."""

    small: PipelineSizeBucketOut
    medium: PipelineSizeBucketOut
    large: PipelineSizeBucketOut


class PipelineFunnelPathsOut(Schema):
    """Fixed instant/estimating keys (v1 funnel paths)."""

    instant: PipelineFunnelPathOut
    estimating: PipelineFunnelPathOut


class PipelineScoreboardOut(Schema):
    """v1 SalesPipelineScoreboardSerializer."""

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
    """v1 snapshot stage job entry."""

    id: str
    job_number: int
    name: str
    company_name: str
    hours: float
    value: float
    days_in_stage: int


class PipelineStageOut(Schema):
    """v1 snapshot stage entry."""

    count: int
    hours_total: float
    value_total: float
    avg_days_in_stage: float
    jobs: list[PipelineStageJobOut]


class PipelineSnapshotOut(Schema):
    """v1 SalesPipelineSnapshotSerializer."""

    as_of: date
    draft: PipelineStageOut
    awaiting_approval: PipelineStageOut


class PipelineVelocityLegOut(Schema):
    """v1 velocity leg entry."""

    median_days: float | None
    p80_days: float | None
    sample_size: int


class PipelineVelocityOut(Schema):
    """v1 SalesPipelineVelocitySerializer."""

    draft_to_quote_sent: PipelineVelocityLegOut
    quote_sent_to_resolved: PipelineVelocityLegOut
    created_to_approved: PipelineVelocityLegOut


class PipelineFunnelBucketOut(Schema):
    """v1 conversion-funnel bucket."""

    count: int
    hours: float


class PipelineFunnelOut(Schema):
    """v1 SalesPipelineFunnelSerializer."""

    accepted: PipelineFunnelBucketOut
    rejected: PipelineFunnelBucketOut
    waiting: PipelineFunnelBucketOut
    direct: PipelineFunnelBucketOut
    still_draft: PipelineFunnelBucketOut


class PipelineTrendWeekOut(Schema):
    """v1 trend week entry."""

    week_start: date
    week_end: date
    approved_hours: float
    approved_hours_per_working_day: float
    acceptance_rate_by_hours: float | None
    pipeline_hours_at_week_end: float
    median_velocity_days: float | None
    working_days: int


class PipelineRollingAverageOut(Schema):
    """v1 trend rolling-average entry."""

    week_start: date
    rolling_avg_approved_hours: float


class PipelineTrendOut(Schema):
    """v1 SalesPipelineTrendSerializer."""

    weeks: list[PipelineTrendWeekOut]
    rolling_average: list[PipelineRollingAverageOut]


class PipelineWarningJobOut(Schema):
    """v1 warning sample job."""

    id: str
    job_number: int | None
    name: str


class PipelineWarningOut(Schema):
    """v1 SalesPipelineWarningSerializer."""

    code: str
    section: str
    count: int
    sample_jobs: list[PipelineWarningJobOut]


class SalesPipelineResponse(Schema):
    """v1 SalesPipelineResponseSerializer."""

    period: PipelinePeriodOut
    scoreboard: PipelineScoreboardOut
    pipeline_snapshot: PipelineSnapshotOut
    velocity: PipelineVelocityOut
    conversion_funnel: PipelineFunnelOut
    trend: PipelineTrendOut
    warnings: list[PipelineWarningOut]


class PayrollStaffWeekRowOut(Schema):
    """v1 PayrollStaffWeekRowSerializer."""

    name: str
    xero_hours: float
    xero_timesheet_hours: float
    xero_leave_hours: float
    xero_gross: float
    xero_rate: float
    jm_hours: float
    jm_cost: float
    jm_rate: float
    hours_diff: float
    cost_diff: float
    hours_cost_impact: float
    rate_cost_impact: float
    status: str


class PayrollWeekTotalsOut(Schema):
    """v1 week totals."""

    xero_gross: float
    jm_cost: float
    diff: float
    xero_hours: float
    jm_hours: float


class PayrollWeekOut(Schema):
    """v1 PayrollWeekSerializer."""

    week_start: date
    xero_period_start: date | None
    xero_period_end: date | None
    payment_date: date | None
    totals: PayrollWeekTotalsOut
    mismatch_count: int
    staff: list[PayrollStaffWeekRowOut]


class PayrollStaffSummaryOut(Schema):
    """v1 staff summary."""

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


class PayrollHeatmapRowOut(Schema):
    """v1 heatmap row."""

    week_start: date
    cells: dict[str, float | None]


class PayrollHeatmapOut(Schema):
    """v1 heatmap."""

    staff_names: list[str]
    rows: list[PayrollHeatmapRowOut]


class PayrollGrandTotalsOut(Schema):
    """v1 grand totals."""

    xero_gross: float
    jm_cost: float
    diff: float
    diff_pct: float


class PayrollReconciliationResponse(Schema):
    """v1 PayrollReconciliationResponseSerializer."""

    weeks: list[PayrollWeekOut]
    staff_summaries: list[PayrollStaffSummaryOut]
    heatmap: PayrollHeatmapOut
    grand_totals: PayrollGrandTotalsOut


class PayrollDateRangeResponse(Schema):
    """v1 PayrollDateRangeResponseSerializer."""

    aligned_start: date
    aligned_end: date
