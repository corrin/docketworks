"""Pydantic schemas for the timesheet router (wire shapes match v1 frontend/schema.yml).

Success bodies mirror v1's DRF serializers in ``apps/timesheet/serializers/``;
the services in ``apps/timesheet/services/`` build matching TypedDict data.
Error bodies use the v2 envelope (ADR 0013).
"""

from datetime import date, datetime, time
from decimal import Decimal
from uuid import UUID

from ninja import Schema
from pydantic import Field

from apps.job.schemas import JobLabourRateOut

# v1 request-validation bounds for workshop time entries (DRF DecimalField
# max_digits/decimal_places/min_value, mirrored in frontend/schema.yml).
HOURS_MIN = Decimal("0.01")
HOURS_LIMIT = Decimal("100000")  # max_digits=7, decimal_places=2
MULTIPLIER_MIN = Decimal("0")
MULTIPLIER_LIMIT = Decimal("100")  # max_digits=4, decimal_places=2
DESCRIPTION_MAX_LENGTH = 255

# ── Daily timesheet ──────────────────────────────────────────────────────


class JobBreakdownOut(Schema):
    """v1 JobBreakdownSerializer."""

    job_id: str
    job_number: int
    job_name: str
    company: str
    hours: float
    revenue: float
    cost: float
    is_billable: bool


class StaffDailyDataOut(Schema):
    """v1 StaffDailyDataSerializer."""

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
    job_breakdown: list[JobBreakdownOut]
    entry_count: int
    alerts: list[str]
    is_weekend: bool
    weekend_enabled: bool


class DailyTotalsOut(Schema):
    """v1 DailyTotalsSerializer."""

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


class SummaryStatsOut(Schema):
    """v1 SummaryStatsSerializer (shared by the daily and weekly payloads)."""

    total_staff: int
    complete_staff: int
    partial_staff: int
    missing_staff: int
    completion_rate: float


class DailyTimesheetSummaryOut(Schema):
    """v1 DailyTimesheetSummarySerializer.

    ``day_type`` is declared in v1's serializer but the view never supplied it,
    so it never reached the wire and is not modelled here.
    """

    date: date
    staff_data: list[StaffDailyDataOut]
    daily_totals: DailyTotalsOut
    summary_stats: SummaryStatsOut
    weekend_enabled: bool
    is_weekend: bool


# ── Weekly timesheet ─────────────────────────────────────────────────────


class WeeklyStaffDayOut(Schema):
    """v1 WeeklyStaffDataWeeklyHoursSerializer."""

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


class WeeklyStaffDataOut(Schema):
    """v1 WeeklyStaffDataSerializer."""

    staff_id: UUID
    name: str
    weekly_hours: list[WeeklyStaffDayOut]
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


class WeeklySummaryOut(Schema):
    """v1 WeeklySummarySerializer."""

    total_hours: float
    staff_count: int
    billable_percentage: float | None


class JobMetricsOut(Schema):
    """v1 JobMetricsSerializer."""

    total_estimated_profit: float
    total_actual_profit: float
    total_profit: float


class WeeklyNavigationOut(Schema):
    """Week navigation block v1's view attached to the weekly payload."""

    prev_week_date: str
    next_week_date: str
    current_week_date: str


class WeeklyTimesheetDataOut(Schema):
    """v1 WeeklyTimesheetDataSerializer."""

    start_date: str
    end_date: str
    week_days: list[str]
    staff_data: list[WeeklyStaffDataOut]
    weekly_summary: WeeklySummaryOut
    job_metrics: JobMetricsOut
    summary_stats: SummaryStatsOut
    export_mode: str
    is_current_week: bool
    navigation: WeeklyNavigationOut | None
    weekend_enabled: bool
    week_type: str


# ── Entry reference data (staff + jobs) ──────────────────────────────────


class TimesheetStaffOut(Schema):
    """v1 ModernStaffSerializer (camelCase keys are v1's wire names)."""

    id: str
    name: str
    firstName: str  # noqa: N815 -- v1 wire name
    lastName: str  # noqa: N815 -- v1 wire name
    email: str
    icon_url: str | None
    wageRate: Decimal  # noqa: N815 -- v1 wire name


class StaffListResponse(Schema):
    """v1 StaffListResponseSerializer."""

    staff: list[TimesheetStaffOut]
    total_count: int


class TimesheetJobOut(Schema):
    """v1 ModernTimesheetJobSerializer."""

    id: UUID
    job_number: int
    name: str
    company_name: str | None
    status: str
    labour_rates: list[JobLabourRateOut]
    has_actual_costset: bool
    leave_type: str | None
    estimated_hours: float | None
    default_xero_pay_item_id: UUID | None
    default_xero_pay_item_name: str | None
    shop_job: bool
    is_urgent: bool


class JobsListResponse(Schema):
    """v1 JobsListResponseSerializer."""

    jobs: list[TimesheetJobOut]
    total_count: int


# ── Workshop "my time" self-service ──────────────────────────────────────


class WorkshopTimesheetEntryOut(Schema):
    """v1 WorkshopTimesheetEntrySerializer."""

    id: UUID
    job_id: UUID
    job_number: int
    job_name: str
    company_name: str
    description: str
    hours: float
    accounting_date: date
    start_time: time | None
    end_time: time | None
    is_billable: bool
    wage_rate_multiplier: float
    bill_rate_multiplier: float
    created_at: datetime
    updated_at: datetime


class WorkshopTimesheetSummaryOut(Schema):
    """v1 WorkshopTimesheetSummarySerializer."""

    total_hours: float
    billable_hours: float
    non_billable_hours: float
    total_cost: float
    total_revenue: float


class WorkshopTimesheetListResponse(Schema):
    """v1 WorkshopTimesheetListResponseSerializer."""

    date: date
    entries: list[WorkshopTimesheetEntryOut]
    summary: WorkshopTimesheetSummaryOut


class WorkshopTimesheetEntryRequest(Schema):
    """v1 WorkshopTimesheetEntryRequestSerializer.

    The bounds are v1's DecimalField/CharField constraints, which are also what
    frontend/schema.yml documents: ``hours`` is min 0.01 (max_digits=7,
    decimal_places=2 -> below 100000) and the multipliers are min 0 (max_digits=4
    -> below 100). Without them a workshop staff member could book negative
    hours, which lands negative cost and revenue in the actual CostSet and every
    downstream total (the costing surface has always rejected it).
    """

    job_id: UUID
    accounting_date: date
    hours: Decimal = Field(ge=HOURS_MIN, lt=HOURS_LIMIT)
    description: str | None = Field(None, max_length=DESCRIPTION_MAX_LENGTH)
    start_time: time | None = None
    end_time: time | None = None
    is_billable: bool = True
    wage_rate_multiplier: Decimal = Field(Decimal("1.00"), ge=MULTIPLIER_MIN, lt=MULTIPLIER_LIMIT)
    bill_rate_multiplier: Decimal | None = Field(None, ge=MULTIPLIER_MIN, lt=MULTIPLIER_LIMIT)


class WorkshopTimesheetEntryUpdateRequest(Schema):
    """v1 WorkshopTimesheetEntryUpdateSerializer (PATCH; entry_id identifies the row).

    Same bounds as the create request — v1 declared them on both serializers.
    """

    entry_id: UUID
    job_id: UUID | None = None
    accounting_date: date | None = None
    hours: Decimal | None = Field(None, ge=HOURS_MIN, lt=HOURS_LIMIT)
    description: str | None = Field(None, max_length=DESCRIPTION_MAX_LENGTH)
    start_time: time | None = None
    end_time: time | None = None
    is_billable: bool | None = None
    wage_rate_multiplier: Decimal | None = Field(None, ge=MULTIPLIER_MIN, lt=MULTIPLIER_LIMIT)
    bill_rate_multiplier: Decimal | None = Field(None, ge=MULTIPLIER_MIN, lt=MULTIPLIER_LIMIT)


# ── Xero Payroll pay runs ────────────────────────────────────────────────


class PayRunListItemOut(Schema):
    """v1 PayRunListItemSerializer."""

    id: UUID
    xero_id: UUID
    period_start_date: date
    period_end_date: date
    payment_date: date
    pay_run_status: str
    xero_url: str


class PayRunListResponse(Schema):
    """v1 PayRunListResponseSerializer."""

    pay_runs: list[PayRunListItemOut]
    next_postable_week_start_date: date | None
    next_postable_week_end_date: date | None


class CreatePayRunRequest(Schema):
    """v1 CreatePayRunSerializer."""

    week_start_date: date


class CreatePayRunResponse(Schema):
    """v1 CreatePayRunResponseSerializer."""

    id: UUID
    xero_id: UUID
    status: str
    period_start_date: date
    period_end_date: date
    payment_date: date
    xero_url: str


class PayRunSyncResponse(Schema):
    """v1 PayRunSyncResponseSerializer."""

    synced: bool
    fetched: int
    created: int
    updated: int


class PostWeekToXeroRequest(Schema):
    """v1 PostWeekToXeroSerializer."""

    staff_ids: list[UUID]
    week_start_date: date


class PostWeekToXeroStartResponse(Schema):
    """v1 PostWeekToXeroStartResponseSerializer."""

    task_id: UUID
    stream_url: str
