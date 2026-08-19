"""The timesheet domain's ninja router (thin translators over apps.timesheet.services).

Management endpoints under ``/api/timesheets/`` expose daily and weekly
summaries, entry reference data, and Xero pay-run operations.

The self-service ``/api/job/workshop/timesheets/`` surface manages a staff
member's own entries. Although its URL is under ``/api/job/``, the code lives
here because timesheet entry has one implementation home (ADR 0039).

Authorization is split by sensitivity:

- every ``/api/timesheets/`` endpoint: ``IsAuthenticated + CanManageTimesheets``
  → superuser only (this surface exposes other staff members' pay data)
- ``/api/job/workshop/timesheets/``: ``IsAuthenticated`` only — any staff
  member, reading and writing ONLY their own entries. Ownership is enforced in
  the service on every write (``meta.staff_id``), never by the router.

Phase 4 (Xero) seams: creating and refreshing pay runs, the postable-week rule
when a calendar has no pay runs yet, and the SSE stream that actually posts a
week to Xero Payroll (``payroll/post-staff-week/stream/{task_id}/`` — not
routed here; ``post-staff-week/`` still registers the task).

Integration wiring (config/api.py): ``api.add_router("/", router)`` — the paths
below carry their own prefixes.
"""

import logging
from datetime import date, datetime, timedelta
from uuid import UUID

from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import HttpRequest
from django.utils import timezone
from ninja import Router
from ninja.errors import HttpError
from ninja.responses import Status

from apps.accounts.models import Staff
from apps.core.auth import CookieJWTAuth, SuperuserCookieJWTAuth
from apps.job.models import Job
from apps.job.models.costing import CostLine
from apps.timesheet.schemas import (
    CreatePayRunRequest,
    CreatePayRunResponse,
    DailyTimesheetSummaryOut,
    JobsListResponse,
    PayRunListResponse,
    PayRunSyncResponse,
    PostWeekToXeroRequest,
    PostWeekToXeroStartResponse,
    StaffDailyDataOut,
    StaffListResponse,
    TimesheetEntriesOut,
    WeeklyTimesheetDataOut,
    WeekPostingStatusResponse,
    WorkshopTimesheetEntryOut,
    WorkshopTimesheetEntryRequest,
    WorkshopTimesheetEntryUpdateRequest,
    WorkshopTimesheetListResponse,
)
from apps.timesheet.services import (
    daily_timesheet_service,
    payroll_service,
    timesheet_entry_options,
    weekly_timesheet_service,
    workshop_timesheet_service,
)
from apps.timesheet.services.workshop_timesheet_service import (
    WorkshopEntryCreateData,
    WorkshopEntryUpdateData,
)

logger = logging.getLogger(__name__)

router = Router()

# The management surface is superuser-only.
manage_auth = SuperuserCookieJWTAuth()
# The self-service surface is available to any authenticated staff member.
self_service_auth = CookieJWTAuth()

DATE_FORMAT_ERROR = "Invalid date format. Use YYYY-MM-DD"


def _parse_date(raw: str) -> date:
    """Parse a YYYY-MM-DD path/query value, 400 on anything else."""
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()  # noqa: DTZ007 -- date-only value
    except ValueError as exc:
        raise HttpError(400, DATE_FORMAT_ERROR) from exc


def _validation_message(exc: DjangoValidationError) -> str:
    """Flatten a model/pipeline ValidationError into a single message (house pattern)."""
    return "; ".join(exc.messages)


def _staff(request: HttpRequest) -> Staff:
    """Return the authenticated staff member (the auth class guarantees one)."""
    user = request.user
    if not isinstance(user, Staff):  # pragma: no cover - guaranteed by the auth class
        raise HttpError(401, "Authentication credentials were not provided.")
    return user


# ── Daily ────────────────────────────────────────────────────────────────


@router.get(
    "/timesheets/daily/{target_date}/",
    auth=manage_auth,
    operation_id="getDailyTimesheetSummaryByDate",
    response=DailyTimesheetSummaryOut,
    summary="Get daily timesheet summary for all staff",
    tags=["timesheets"],
)
def get_daily_timesheet_summary_by_date(
    request: HttpRequest, target_date: str
) -> daily_timesheet_service.DailyTimesheetSummaryData:
    """Daily timesheet summary for every displayable staff member."""
    return daily_timesheet_service.get_daily_summary(_parse_date(target_date))


@router.get(
    "/timesheets/staff/{staff_id}/daily/{target_date}/",
    auth=manage_auth,
    operation_id="getStaffDailyTimesheetDetailByDate",
    response=StaffDailyDataOut,
    summary="Get detailed timesheet data for a specific staff member",
    tags=["timesheets"],
)
def get_staff_daily_timesheet_detail_by_date(
    request: HttpRequest, staff_id: str, target_date: str
) -> daily_timesheet_service.StaffDailyData:
    """One staff member's row from the daily summary; 404 when they are absent."""
    detail = daily_timesheet_service.get_staff_daily_detail(staff_id, _parse_date(target_date))
    if detail is None:
        raise HttpError(404, "Staff member not found")
    return detail


# ── Weekly ───────────────────────────────────────────────────────────────


@router.get(
    "/timesheets/weekly/",
    auth=manage_auth,
    operation_id="timesheets_weekly_retrieve",
    response=WeeklyTimesheetDataOut,
    summary="Weekly overview with payroll data (Mon–Sun/Mon–Fri)",  # noqa: RUF001 -- En dashes are intentional UI copy.
    tags=["timesheets"],
)
def timesheets_weekly_retrieve(
    request: HttpRequest, start_date: str | None = None
) -> weekly_timesheet_service.WeeklyTimesheetData:
    """Weekly timesheet data with payroll fields; defaults to the current week."""
    if start_date:
        week_start = _parse_date(start_date)
    else:
        today = timezone.localdate()
        week_start = today - timedelta(days=today.weekday())
    return weekly_timesheet_service.get_weekly_overview(week_start)


# ── Entry reference data ─────────────────────────────────────────────────


@router.get(
    "/timesheets/staff/",
    auth=manage_auth,
    operation_id="timesheets_staff_retrieve",
    response=StaffListResponse,
    summary="Returns staff members excluding system and users for a specific date",
    tags=["timesheets"],
)
def timesheets_staff_retrieve(
    request: HttpRequest, date: str | None = None
) -> timesheet_entry_options.TimesheetStaffListData:
    """Staff selectable for time entry on a date; defaults to today.

    The parameter is named ``date`` because that is the public query-parameter name
    and the generated client sends it.
    """
    target_date = _parse_date(date) if date else timezone.localdate()
    return timesheet_entry_options.get_staff_for_date(target_date)


@router.get(
    "/job/timesheet/entries/",
    auth=manage_auth,
    operation_id="job_timesheet_entries_retrieve",
    response=TimesheetEntriesOut,
    summary="Any staff member's time lines for a date, with the day summary",
    tags=["timesheets"],
)
def job_timesheet_entries_retrieve(
    request: HttpRequest, staff_id: UUID, date: str
) -> workshop_timesheet_service.ManagementDayData:
    """Serve the management entry grid's read: CostLine-shaped lines for one staff/day.

    Lives on the timesheet router (one implementation home for timesheet
    entry, ADR 0039) but keeps the ``/api/job/timesheet/`` URL and the
    ``job_*`` operation id — the ``job_workshop_timesheets_*`` precedent.
    The parameter is named ``date`` because that is the public query-parameter
    name and the generated client sends it.
    """
    entry_date = _parse_date(date)
    try:
        staff = Staff.objects.get(id=staff_id)
    except Staff.DoesNotExist as exc:
        raise HttpError(404, f"Staff member {staff_id} not found") from exc
    return workshop_timesheet_service.management_day_data(staff, entry_date)


@router.get(
    "/timesheets/jobs/",
    auth=manage_auth,
    operation_id="timesheets_jobs_retrieve",
    response=JobsListResponse,
    summary="Get list of active jobs for timesheet entries using CostSet system",
    tags=["timesheets"],
)
def timesheets_jobs_retrieve(
    request: HttpRequest, q: str = ""
) -> timesheet_entry_options.TimesheetJobListData:
    """Jobs available for time entry (active, plus recently archived fixed-price).

    With `q`, searches the whole table so a picker can reach an archived job.
    """
    return timesheet_entry_options.get_jobs_for_entry(q)


# ── Xero Payroll pay runs ────────────────────────────────────────────────


@router.get(
    "/timesheets/payroll/pay-runs/",
    auth=manage_auth,
    operation_id="timesheets_payroll_pay_runs_retrieve",
    response=PayRunListResponse,
    summary="List pay runs",
    tags=["timesheets"],
)
def timesheets_payroll_pay_runs_retrieve(request: HttpRequest) -> payroll_service.PayRunListData:
    """All pay runs for the configured payroll calendar (local mirror)."""
    return payroll_service.list_pay_runs()


@router.post(
    "/timesheets/payroll/pay-runs/create",
    auth=manage_auth,
    operation_id="timesheets_payroll_pay_runs_create_create",
    response={201: CreatePayRunResponse},
    summary="Create pay run for a week",
    tags=["timesheets"],
)
def timesheets_payroll_pay_runs_create_create(
    request: HttpRequest, payload: CreatePayRunRequest
) -> Status[payroll_service.CreatedPayRunData]:
    """Create a new pay run for the specified week (Phase 4 seam: Xero write)."""
    try:
        created = payroll_service.create_pay_run_for_week(payload.week_start_date)
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc
    return Status(201, created)


@router.post(
    "/timesheets/payroll/pay-runs/refresh",
    auth=manage_auth,
    operation_id="timesheets_payroll_pay_runs_refresh_create",
    response=PayRunSyncResponse,
    summary="Refresh cached pay runs from Xero",
    tags=["timesheets"],
)
def timesheets_payroll_pay_runs_refresh_create(
    request: HttpRequest,
) -> payroll_service.PayRunSyncData:
    """Synchronise the local pay-run mirror with Xero (Phase 4 seam)."""
    return payroll_service.refresh_pay_run_mirror()


@router.get(
    "/timesheets/payroll/week-status/",
    auth=manage_auth,
    operation_id="timesheets_payroll_week_status_retrieve",
    response=WeekPostingStatusResponse,
    summary="What Xero holds for the week, beside what was recorded",
    tags=["timesheets"],
)
def timesheets_payroll_week_status_retrieve(
    request: HttpRequest, week_start_date: str
) -> payroll_service.WeekPostingStatusData:
    """Ask Xero what it holds for each staff member's week.

    Opus: Separate from the weekly overview on purpose (ADR 0007): this one calls
    Xero, and the grid must keep rendering when Xero is unreachable.

    ``week_start_date`` is required rather than defaulting to this week. A
    default would make a bare GET call Xero, and the one caller always knows
    which week it is showing.
    """
    # Opus: NotAPayrollWeekError is a typed InvalidInputError; every other provider
    # or data-shape failure remains unexpected and reaches the 500 handler.
    return payroll_service.posting_status_for_week(_parse_date(week_start_date))


@router.post(
    "/timesheets/payroll/post-staff-week/",
    auth=manage_auth,
    operation_id="timesheets_payroll_post_staff_week_create",
    response=PostWeekToXeroStartResponse,
    summary="Start posting weekly timesheets to Xero Payroll",
    tags=["timesheets"],
)
def timesheets_payroll_post_staff_week_create(
    request: HttpRequest, payload: PostWeekToXeroRequest
) -> payroll_service.PostWeekStartData:
    """Register the posting task and return its SSE stream URL."""
    try:
        return payroll_service.start_post_week_task(payload.staff_ids, payload.week_start_date)
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc


# ── Workshop "my time" self-service (/api/job/) ──────────────────────────


@router.get(
    "/job/workshop/timesheets/",
    auth=self_service_auth,
    operation_id="job_workshop_timesheets_retrieve",
    response=WorkshopTimesheetListResponse,
    summary="Return all timesheet entries for the staff member on a given date",
    tags=["job"],
)
def job_workshop_timesheets_retrieve(
    request: HttpRequest, date: str | None = None
) -> workshop_timesheet_service.WorkshopDayData:
    """Return the staff member's own entries for a date (defaults to today)."""
    try:
        entry_date = workshop_timesheet_service.resolve_entry_date(date)
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc
    return workshop_timesheet_service.list_entries(_staff(request), entry_date)


def _create_payload(payload: WorkshopTimesheetEntryRequest) -> WorkshopEntryCreateData:
    """Translate the validated create request into the service's payload."""
    data: WorkshopEntryCreateData = {
        "job_id": payload.job_id,
        "accounting_date": payload.accounting_date,
        "hours": payload.hours,
        "description": payload.description,
        "is_billable": payload.is_billable,
        "wage_rate_multiplier": payload.wage_rate_multiplier,
    }
    if payload.start_time is not None:
        data["start_time"] = payload.start_time
    if payload.end_time is not None:
        data["end_time"] = payload.end_time
    if payload.bill_rate_multiplier is not None:
        data["bill_rate_multiplier"] = payload.bill_rate_multiplier
    return data


@router.post(
    "/job/workshop/timesheets/",
    auth=self_service_auth,
    operation_id="job_workshop_timesheets_create",
    response={201: WorkshopTimesheetEntryOut},
    summary="Create a new timesheet entry for the authenticated staff",
    tags=["job"],
)
def job_workshop_timesheets_create(
    request: HttpRequest, payload: WorkshopTimesheetEntryRequest
) -> Status[workshop_timesheet_service.WorkshopEntryData]:
    """Create a time entry owned by the authenticated staff member."""
    try:
        entry = workshop_timesheet_service.create_entry(_staff(request), _create_payload(payload))
    except Job.DoesNotExist as exc:
        raise HttpError(404, "Job not found.") from exc
    except DjangoValidationError as exc:
        # Unpriceable entry (no wage rate, no pay item, no labour rate): the
        # caller's data is wrong, so 400 with the specific cause (ADR 0038).
        raise HttpError(400, _validation_message(exc)) from exc
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc
    return Status(201, entry)


def _update_payload(payload: WorkshopTimesheetEntryUpdateRequest) -> WorkshopEntryUpdateData:
    """Translate the validated PATCH request into the service's partial payload."""
    provided = payload.model_fields_set
    data: WorkshopEntryUpdateData = {"entry_id": payload.entry_id}
    if "job_id" in provided:
        data["job_id"] = payload.job_id
    if "accounting_date" in provided:
        data["accounting_date"] = payload.accounting_date
    if "hours" in provided:
        data["hours"] = payload.hours
    if "description" in provided:
        data["description"] = payload.description
    if "start_time" in provided:
        data["start_time"] = payload.start_time
    if "end_time" in provided:
        data["end_time"] = payload.end_time
    if "is_billable" in provided:
        data["is_billable"] = payload.is_billable
    if "wage_rate_multiplier" in provided:
        data["wage_rate_multiplier"] = payload.wage_rate_multiplier
    if "bill_rate_multiplier" in provided:
        data["bill_rate_multiplier"] = payload.bill_rate_multiplier
    return data


@router.patch(
    "/job/workshop/timesheets/",
    auth=self_service_auth,
    operation_id="job_workshop_timesheets_partial_update",
    response=WorkshopTimesheetEntryOut,
    summary="Update an existing timesheet entry belonging to the staff member",
    tags=["job"],
)
def job_workshop_timesheets_partial_update(
    request: HttpRequest, payload: WorkshopTimesheetEntryUpdateRequest
) -> workshop_timesheet_service.WorkshopEntryData:
    """Update one of the authenticated staff member's own entries."""
    data = _update_payload(payload)
    if len(data) <= 1:
        raise HttpError(400, "At least one field besides entry_id must be provided.")
    try:
        return workshop_timesheet_service.update_entry(_staff(request), data)
    except CostLine.DoesNotExist as exc:
        raise HttpError(404, "Timesheet entry not found.") from exc
    except Job.DoesNotExist as exc:
        raise HttpError(404, "Job not found.") from exc
    except DjangoValidationError as exc:
        raise HttpError(400, _validation_message(exc)) from exc
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc


@router.delete(
    "/job/workshop/timesheets/",
    auth=self_service_auth,
    operation_id="job_workshop_timesheets_destroy",
    response={204: None},
    summary="Delete a timesheet entry belonging to the staff member",
    tags=["job"],
)
def job_workshop_timesheets_destroy(request: HttpRequest, entry_id: UUID) -> Status[None]:
    """Delete one of the authenticated staff member's own entries."""
    try:
        workshop_timesheet_service.delete_entry(_staff(request), entry_id)
    except CostLine.DoesNotExist as exc:
        raise HttpError(404, "Timesheet entry not found.") from exc
    return Status(204, None)
