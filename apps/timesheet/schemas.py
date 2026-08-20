"""Pydantic wire contracts for the timesheet router.

Timesheet services build matching TypedDict data, and error responses use the
standard envelope from ADR 0013.
"""

from datetime import date, datetime, time
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from ninja import Schema
from pydantic import Field

from apps.accounting.types import PayrollPostingMode
from apps.core.schemas import Quantity, ResponseSchema, omittable
from apps.job.schemas import CostLineOut, JobLabourRateOut

# These bounds keep workshop inputs representable by their decimal columns and
# stop negative hours or multipliers before they affect costing totals.
HOURS_MIN = Decimal("0.01")
HOURS_LIMIT = Decimal("100000")  # max_digits=7, decimal_places=2
MULTIPLIER_MIN = Decimal("0")
MULTIPLIER_LIMIT = Decimal("100")  # max_digits=4, decimal_places=2
DESCRIPTION_MAX_LENGTH = 255

# ── Daily timesheet ──────────────────────────────────────────────────────


#: Opus: The Docketworks leave category, as a named union rather than free text.
#: This carried the Xero pay item's NAME, which an admin can edit from the
#: leave-settings screen — so a rename changed what the weekly grid said a day
#: was, all the way into the browser (ADR 0007's "Do not", ADR 0028).
type LeaveCodeOut = Literal[
    "annual_leave", "sick_leave", "unpaid_leave", "bereavement_leave", "public_holiday"
]


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
    day_status: str
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
    hours: Quantity
    billable_hours: Quantity
    scheduled_hours: Quantity
    day_status: str
    leave_type: LeaveCodeOut | None
    has_leave: bool
    billed_hours: Quantity
    unbilled_hours: Quantity
    overtime_1_5x_hours: Quantity
    overtime_2x_hours: Quantity
    sick_leave_hours: Quantity
    annual_leave_hours: Quantity
    bereavement_leave_hours: Quantity
    other_leave_hours: Quantity
    daily_cost: Quantity
    daily_base_cost: Quantity


class WeeklyStaffDataOut(Schema):
    """Wire contract for WeeklyStaffDataOut."""

    staff_id: UUID
    staff_name: str
    weekly_hours: list[WeeklyStaffDayOut]
    total_hours: Quantity
    total_billable_hours: Quantity
    total_scheduled_hours: Quantity
    billable_percentage: Quantity
    week_status: str
    total_billed_hours: Quantity
    total_unbilled_hours: Quantity
    total_overtime_hours: Quantity
    total_overtime_1_5x_hours: Quantity
    total_overtime_2x_hours: Quantity
    total_sick_leave_hours: Quantity
    total_annual_leave_hours: Quantity
    total_bereavement_leave_hours: Quantity
    total_other_leave_hours: Quantity
    weekly_cost: Quantity
    weekly_base_cost: Quantity
    pay_basis: str | None
    expected_hours: Quantity
    variance_hours: Quantity


class WeeklySummaryOut(Schema):
    """Wire contract for WeeklySummaryOut."""

    total_hours: Quantity
    staff_count: int
    billable_percentage: Quantity | None


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
    office_email: str
    icon_url: str | None
    wageRate: Decimal  # noqa: N815 -- public API uses camelCase
    pay_basis: str | None


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


class TimesheetCostLineOut(CostLineOut):
    """A time line for the management entry grid, carrying its job identity.

    The grid's job is per-row (unlike the job costing grid, where the page
    owns one job), so each line names its job for the picker trigger text,
    the urgent badge lookup and the company column.
    """

    job_id: UUID
    job_number: int
    job_name: str
    company_name: str | None


class TimesheetEntriesStaffOut(Schema):
    """Wire contract for TimesheetEntriesStaffOut."""

    id: UUID
    name: str
    first_name: str
    last_name: str


class TimesheetEntriesSummaryOut(Schema):
    """Wire contract for TimesheetEntriesSummaryOut."""

    total_hours: float
    billable_hours: float
    non_billable_hours: float
    total_cost: float
    total_revenue: float
    entry_count: int
    scheduled_hours: float


class TimesheetEntriesOut(Schema):
    """Wire contract for TimesheetEntriesOut (the management day view)."""

    cost_lines: list[TimesheetCostLineOut]
    staff: TimesheetEntriesStaffOut
    date: date
    summary: TimesheetEntriesSummaryOut


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
    job_id: UUID = omittable(UUID(int=0))
    accounting_date: date = omittable(date.min)
    hours: Annotated[Decimal, Field(ge=HOURS_MIN, lt=HOURS_LIMIT)] = omittable(HOURS_MIN)
    description: str | None = Field(None, max_length=DESCRIPTION_MAX_LENGTH)
    start_time: time | None = None
    end_time: time | None = None
    is_billable: bool = omittable(False)
    wage_rate_multiplier: Annotated[Decimal, Field(ge=MULTIPLIER_MIN, lt=MULTIPLIER_LIMIT)] = (
        omittable(MULTIPLIER_MIN)
    )
    bill_rate_multiplier: Annotated[Decimal, Field(ge=MULTIPLIER_MIN, lt=MULTIPLIER_LIMIT)] = (
        omittable(MULTIPLIER_MIN)
    )


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


#: Opus: How a posting run stands. ONE field, where there were five event kinds
#: and a `TERMINAL_EVENTS` set that disagreed with the client about which ended
#: a run: the task published `error` then `done`, the stream returned on the
#: `error`, and the client — which keys "finished" off `done` — reconnected three
#: times and reported "the run ended without reporting an outcome". A real
#: failure with an actionable message became a silent quarter-hour. A run cannot
#: be in two of these at once, so the disagreement has nowhere to live.
type PayrollRunStatus = Literal["queued", "running", "succeeded", "failed"]


class StaffWeekPostResultOut(ResponseSchema):
    """One staff member's outcome, as the run reports it.

    Opus: Built by `model_validate` off the frozen `StaffWeekPostResult` dataclass
    rather than a hand-written flattening step. The flattening was a second
    declaration of these fields, and a third lived in TypeScript.
    """

    # Opus: No defaults. This is a ResponseSchema — every declared field is in the
    # body — and a default on a Quantity published `default: "0"` against a
    # numeric type, because a Decimal default serialises as a string. The
    # dataclass this is validated from carries the defaults; the wire does not
    # need a second opinion about them.
    staff_id: str
    staff_name: str
    success: bool
    timesheet_id: str | None
    entries_posted: int
    work_hours: Quantity
    other_leave_hours: Quantity
    leave_hours: Quantity
    skipped: bool
    reason: str | None
    has_entries: bool
    error: str | None
    posting_mode: PayrollPostingMode
    salary_timesheet_removed: bool


class PayrollPostRunOut(ResponseSchema):
    """The whole state of a payroll posting run.

    Opus: Latest-state-wins, the contract ADR 0047 already proves with
    data-versions: every push carries the complete current document, so a client
    that connects late, reconnects, or reloads needs no replay and no offset —
    it needs the present. The append-only event log this replaces existed to
    make replay exact, which is a problem this shape does not have.

    `updated_at` is the ordering guard. A catch-up read can be in flight when a
    push lands, and the older answer would otherwise overwrite a finished run
    with a running one, leaving a panel spinning forever.
    """

    run_id: UUID
    week_start_date: date
    status: PayrollRunStatus
    total: int
    completed: int
    successful: int
    failed: int
    current_staff_name: str | None
    #: Opus: A batch-level refusal or failure, verbatim (ADR 0038). This is the
    #: field that was unreachable: "Xero locks leave while the employee is in a
    #: draft pay run — delete the draft for 2026-07-13, then post again" is
    #: exactly what an operator needs and never saw.
    message: str | None
    updated_at: datetime
    results: list[StaffWeekPostResultOut]


class PayrollRunsOut(ResponseSchema):
    """Every payroll run this organisation currently has state for.

    Opus: A named slot rather than a discriminated union: the slot IS the kind, so
    TypeScript narrows by field access with no ceremony. A second kind — the
    comparison run — becomes a second slot, and the frontend's exhaustiveness
    check makes forgetting to handle it a compile error.
    """

    post: PayrollPostRunOut | None


class PostWeekToXeroStartResponse(Schema):
    """Wire contract for PostWeekToXeroStartResponse.

    Opus: Returns the run's opening document rather than a `stream_url`. The panel
    can render "0 of N" before any push arrives, and the stream path is a client
    constant like `data-versions-stream.ts`'s — a URL is not a contract.
    """

    run: PayrollPostRunOut


class StaffWeekPostingOut(Schema):
    """Wire contract for StaffWeekPostingOut."""

    staff_id: str
    posted: bool
    timesheet_status: str | None
    posted_timesheet_hours: Quantity
    posted_leave_hours: Quantity
    recorded_timesheet_hours: Quantity
    recorded_leave_hours: Quantity
    pay_basis: str | None
    matches: bool


class WeekPostingStatusResponse(Schema):
    """Wire contract for WeekPostingStatusResponse."""

    week_start_date: date
    staff: list[StaffWeekPostingOut]
