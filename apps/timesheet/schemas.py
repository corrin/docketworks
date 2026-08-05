"""Pydantic wire contracts for the timesheet router.

Timesheet services build matching TypedDict data, and error responses use the
standard envelope from ADR 0013.
"""

from datetime import date, datetime, time
from decimal import Decimal
from uuid import UUID

from ninja import Schema
from pydantic import Field

from apps.job.schemas import JobLabourRateOut

# These bounds keep workshop inputs representable by their decimal columns and
# stop negative hours or multipliers before they affect costing totals.
HOURS_MIN = Decimal("0.01")
HOURS_LIMIT = Decimal("100000")  # max_digits=7, decimal_places=2
MULTIPLIER_MIN = Decimal("0")
MULTIPLIER_LIMIT = Decimal("100")  # max_digits=4, decimal_places=2
DESCRIPTION_MAX_LENGTH = 255

# ── Daily timesheet ──────────────────────────────────────────────────────


class JobBreakdownOut(Schema):
    """Wire contract for JobBreakdownOut."""

    job_id: str
    job_number: int
    job_name: str
    company: str
    hours: float
    revenue: float
    cost: float
    is_billable: bool


class StaffDailyDataOut(Schema):
    """Wire contract for StaffDailyDataOut."""

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
    """Wire contract for DailyTotalsOut."""

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
    """Wire contract for SummaryStatsOut."""

    total_staff: int
    complete_staff: int
    partial_staff: int
    missing_staff: int
    completion_rate: float


class DailyTimesheetSummaryOut(Schema):
    """Daily timesheet summary returned by the API.

    ``day_type`` is deliberately absent because the service does not compute or
    supply it; declaring it would advertise a value callers cannot receive.
    """

    date: date
    staff_data: list[StaffDailyDataOut]
    daily_totals: DailyTotalsOut
    summary_stats: SummaryStatsOut
    weekend_enabled: bool
    is_weekend: bool


# ── Weekly timesheet ─────────────────────────────────────────────────────


class WeeklyStaffDayOut(Schema):
    """Wire contract for WeeklyStaffDayOut."""

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
    """Wire contract for WeeklyStaffDataOut."""

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
    """Wire contract for WeeklySummaryOut."""

    total_hours: float
    staff_count: int
    billable_percentage: float | None


class JobMetricsOut(Schema):
    """Wire contract for JobMetricsOut."""

    total_estimated_profit: float
    total_actual_profit: float
    total_profit: float


class WeeklyNavigationOut(Schema):
    """Previous, next, and current week links in the weekly payload."""

    prev_week_date: str
    next_week_date: str
    current_week_date: str


class WeeklyTimesheetDataOut(Schema):
    """Wire contract for WeeklyTimesheetDataOut."""

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
    """Wire contract for TimesheetStaffOut."""

    id: str
    name: str
    firstName: str  # noqa: N815 -- public API uses camelCase
    lastName: str  # noqa: N815 -- public API uses camelCase
    email: str
    icon_url: str | None
    wageRate: Decimal  # noqa: N815 -- public API uses camelCase


class StaffListResponse(Schema):
    """Wire contract for StaffListResponse."""

    staff: list[TimesheetStaffOut]
    total_count: int


class TimesheetJobOut(Schema):
    """Wire contract for TimesheetJobOut."""

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
    """Wire contract for JobsListResponse."""

    jobs: list[TimesheetJobOut]
    total_count: int


# ── Workshop "my time" self-service ──────────────────────────────────────


class WorkshopTimesheetEntryOut(Schema):
    """Wire contract for WorkshopTimesheetEntryOut."""

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
    """Wire contract for WorkshopTimesheetSummaryOut."""

    total_hours: float
    billable_hours: float
    non_billable_hours: float
    total_cost: float
    total_revenue: float


class WorkshopTimesheetListResponse(Schema):
    """Wire contract for WorkshopTimesheetListResponse."""

    date: date
    entries: list[WorkshopTimesheetEntryOut]
    summary: WorkshopTimesheetSummaryOut


class WorkshopTimesheetEntryRequest(Schema):
    """Workshop timesheet-entry creation payload.

    ``hours`` is at least 0.01 and below 100000; multipliers are non-negative
    and below 100. These bounds match storage precision and prevent negative
    cost and revenue from entering the actual CostSet.
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
    """Partial workshop-entry update identified by ``entry_id``.

    Updates use the same storage and costing bounds as creation.
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
    """Wire contract for PayRunListItemOut."""

    id: UUID
    xero_id: UUID
    period_start_date: date
    period_end_date: date
    payment_date: date
    pay_run_status: str
    xero_url: str


class PayRunListResponse(Schema):
    """Wire contract for PayRunListResponse."""

    pay_runs: list[PayRunListItemOut]
    next_postable_week_start_date: date | None
    next_postable_week_end_date: date | None


class CreatePayRunRequest(Schema):
    """Wire contract for CreatePayRunRequest."""

    week_start_date: date


class CreatePayRunResponse(Schema):
    """Wire contract for CreatePayRunResponse."""

    id: UUID
    xero_id: UUID
    status: str
    period_start_date: date
    period_end_date: date
    payment_date: date
    xero_url: str


class PayRunSyncResponse(Schema):
    """Wire contract for PayRunSyncResponse."""

    synced: bool
    fetched: int
    created: int
    updated: int


class PostWeekToXeroRequest(Schema):
    """Wire contract for PostWeekToXeroRequest."""

    staff_ids: list[UUID]
    week_start_date: date


class PostWeekToXeroStartResponse(Schema):
    """Wire contract for PostWeekToXeroStartResponse."""

    task_id: UUID
    stream_url: str
