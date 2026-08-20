"""Leave request workflows and their CostLine payroll projections."""

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Literal, TypedDict
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Prefetch, Q
from django.utils import timezone

from apps.accounting.registry import get_provider
from apps.accounts.models import Staff
from apps.accounts.staff_directory import get_displayable_staff
from apps.job.models.costing import CostLine
from apps.job.services.job_service import CostLineWriteData, create_cost_line
from apps.timesheet.models import LeaveDay, LeaveRequest, LeaveType, PostingSurface
from apps.timesheet.services.hour_categories import scheduled_hours
from apps.timesheet.services.leave_settings import configured_leave_type
from apps.timesheet.services.workshop_timesheet_service import pricing_meta, update_latest_actual


class RequestedDay(TypedDict):
    """A requested leave date and its operator-selected hours."""

    date: date
    hours: Decimal


class PreviewDay(TypedDict):
    """One scheduled date and whether it is available for leave."""

    date: date
    scheduled_hours: Decimal
    hours: Decimal
    available: bool
    reason: str | None


class PreviewData(TypedDict):
    """Leave preview for one staff member and date range."""

    staff_id: str
    staff_name: str
    start_date: date
    end_date: date
    days: list[PreviewDay]
    available_hours: Decimal


class LeaveDayData(TypedDict):
    """One persisted leave day and its payroll line."""

    id: str
    date: date
    hours: Decimal
    cost_line_id: str


class LeaveRequestData(TypedDict):
    """One leave request response."""

    id: str
    staff_id: str
    staff_name: str
    leave_type_code: str
    leave_type_name: str
    start_date: date
    end_date: date
    note: str | None
    source: str
    batch_id: str | None
    total_hours: Decimal
    days: list[LeaveDayData]
    created_at: str


class LeaveSummaryData(TypedDict):
    """Quick figures for the current filtered request set."""

    away_today: int
    upcoming_requests: int
    upcoming_hours: Decimal


class LeaveListData(TypedDict):
    """Current/history list response."""

    scope: str
    requests: list[LeaveRequestData]
    summary: LeaveSummaryData


class SaveResult(TypedDict):
    """Saved request plus conflicts skipped during its final validation."""

    request: LeaveRequestData
    skipped_days: list[PreviewDay]


class OfficeClosurePreviewData(TypedDict):
    """All staff affected by an office-closure range."""

    start_date: date
    end_date: date
    staff: list[PreviewData]
    available_staff: int
    available_hours: Decimal


class OfficeClosureResult(TypedDict):
    """Requests created together for an office closure."""

    batch_id: str
    requests: list[LeaveRequestData]
    skipped_days: list[PreviewDay]


class LeaveBalanceData(TypedDict):
    """Provider balance reduced to display fields."""

    balance: Decimal
    unit: str
    name: str


def _dates(start_date: date, end_date: date) -> list[date]:
    if end_date < start_date:
        raise ValidationError("End date must be on or after start date.")
    return [
        start_date + timedelta(days=offset) for offset in range((end_date - start_date).days + 1)
    ]


def preview_leave(
    *, staff: Staff, start_date: date, end_date: date, exclude_request: LeaveRequest | None = None
) -> PreviewData:
    """Propose scheduled hours and report dates already carrying time."""
    target_dates = _dates(start_date, end_date)
    conflicts = CostLine.objects.filter(
        kind="time",
        cost_set__kind="actual",
        staff=staff,
        accounting_date__range=(start_date, end_date),
    )
    if exclude_request is not None:
        conflicts = conflicts.exclude(leave_day__request=exclude_request)
    conflicting_dates = set(conflicts.values_list("accounting_date", flat=True))

    rows: list[PreviewDay] = []
    for target_date in target_dates:
        rostered = scheduled_hours(staff, target_date, weekend_enabled=True)
        reason: str | None = None
        if not staff.is_active_on(target_date):
            reason = "Outside employment dates"
        elif rostered <= 0:
            reason = "Not a scheduled working day"
        elif target_date in conflicting_dates:
            reason = "Timesheet entry already exists"
        rows.append(
            {
                "date": target_date,
                "scheduled_hours": rostered,
                "hours": rostered,
                "available": reason is None,
                "reason": reason,
            }
        )
    return {
        "staff_id": str(staff.id),
        "staff_name": staff.get_display_full_name(),
        "start_date": start_date,
        "end_date": end_date,
        "days": rows,
        "available_hours": sum((row["hours"] for row in rows if row["available"]), Decimal("0")),
    }


def _validated_days(
    *, preview: PreviewData, requested_days: list[RequestedDay]
) -> tuple[list[RequestedDay], list[PreviewDay]]:
    by_date = {row["date"]: row for row in preview["days"]}
    if len({row["date"] for row in requested_days}) != len(requested_days):
        raise ValidationError("Each leave date may be supplied only once.")

    valid: list[RequestedDay] = []
    skipped: list[PreviewDay] = []
    for requested in requested_days:
        proposal = by_date.get(requested["date"])
        if proposal is None:
            raise ValidationError(f"{requested['date']} is outside the requested date range.")
        if not proposal["available"]:
            skipped.append(proposal)
            continue
        hours = requested["hours"]
        if hours <= 0 or hours > proposal["scheduled_hours"]:
            raise ValidationError(
                f"Hours for {requested['date']} must be greater than zero and no more than "
                f"the scheduled {proposal['scheduled_hours']} hours."
            )
        valid.append({"date": requested["date"], "hours": hours})
    if not valid:
        raise ValidationError("No available leave days remain to save.")
    return valid, skipped


def _request_data(request: LeaveRequest) -> LeaveRequestData:
    days = list(request.days.all())
    return {
        "id": str(request.id),
        "staff_id": str(request.staff_id),
        "staff_name": request.staff.get_display_full_name(),
        "leave_type_code": request.leave_type_id,
        "leave_type_name": request.leave_type.display_name,
        "start_date": request.start_date,
        "end_date": request.end_date,
        "note": request.note,
        "source": request.source,
        "batch_id": str(request.batch_id) if request.batch_id is not None else None,
        "total_hours": sum((day.hours for day in days), Decimal("0")),
        "days": [
            {
                "id": str(day.id),
                "date": day.date,
                "hours": day.hours,
                "cost_line_id": str(day.cost_line_id),
            }
            for day in days
        ],
        "created_at": request.created_at.isoformat(),
    }


def _loaded_request(request_id: UUID) -> LeaveRequest:
    return (
        LeaveRequest.objects.select_related("staff", "leave_type")
        .prefetch_related(Prefetch("days", queryset=LeaveDay.objects.order_by("date")))
        .get(id=request_id)
    )


def _create_days(*, request: LeaveRequest, days: list[RequestedDay], actor: Staff) -> None:
    leave_type = request.leave_type
    job = leave_type.job
    if job is None:
        raise ValidationError(f"{leave_type.display_name} is not fully configured.")
    # Opus: A category Xero pays from its own calculation names NO pay item. The
    # job still carries one as a dropdown default — the column is NOT NULL — and
    # copying it here is what put public-holiday hours on the Timesheets API on
    # top of the line Xero already pays (ADR 0007). CostLine.clean refuses one
    # on these lines, so this is the write side of that invariant, not a second
    # opinion about it.
    if leave_type.posting_surface is PostingSurface.XERO_COMPUTED:
        pay_item_id = None
    else:
        if job.default_xero_pay_item is None:
            raise ValidationError(f"{leave_type.display_name} is not fully configured.")
        pay_item_id = job.default_xero_pay_item.id
    # Fable: The multiplier comes from the category's own paid/unpaid rule, the
    # same LeaveType.is_paid the timesheet grid's leave_wage_rate_multiplier
    # reads — a flat 1 here priced UNPAID leave at the full wage, so a week
    # containing an unpaid day charged the job for hours Xero pays nothing
    # for, and the payroll reconciliation reported a mismatch on every such
    # week (ADR 0007: unpaid's 0x multiplier is what makes it unpaid). First
    # proven live 2026-08-21 by the payroll integration suite.
    wage_multiplier = Decimal("1") if leave_type.is_paid else Decimal("0")
    cost_set = None
    for requested in days:
        meta = pricing_meta(
            staff=request.staff,
            accounting_date=requested["date"],
            wage_rate_multiplier=wage_multiplier,
            bill_rate_multiplier=Decimal("0"),
            is_billable=False,
        )
        data: CostLineWriteData = {
            "kind": "time",
            "desc": request.note or leave_type.display_name,
            "quantity": requested["hours"],
            "accounting_date": requested["date"],
            "meta": meta,
            "xero_pay_item": pay_item_id,
            "staff": request.staff_id,
            "managed_by": "leave",
        }
        line = create_cost_line(job, "actual", data, actor)
        cost_set = line.cost_set
        LeaveDay.objects.create(
            request=request,
            staff=request.staff,
            date=requested["date"],
            hours=requested["hours"],
            cost_line=line,
        )
    if cost_set is not None:
        update_latest_actual(job, cost_set.rev, cost_set.id, actor)


def _delete_days(request: LeaveRequest) -> None:
    day_rows = list(request.days.select_related("cost_line"))
    lines = [day.cost_line for day in day_rows]
    LeaveDay.objects.filter(request=request).delete()
    # Preserve the CostLine model's summary reconciliation on managed deletes.
    for line in lines:
        line.delete()


@transaction.atomic
def create_leave_request(  # noqa: PLR0913 -- one complete leave write contract
    *,
    staff_id: UUID,
    leave_type_code: str,
    start_date: date,
    end_date: date,
    note: str | None,
    requested_days: list[RequestedDay],
    actor: Staff,
    source: str = LeaveRequest.Source.LEAVE,
    batch_id: UUID | None = None,
) -> SaveResult:
    """Create one request and its valid daily payroll lines atomically."""
    staff = Staff.objects.select_for_update().get(id=staff_id)
    leave_type = configured_leave_type(leave_type_code)
    preview = preview_leave(staff=staff, start_date=start_date, end_date=end_date)
    valid, skipped = _validated_days(preview=preview, requested_days=requested_days)
    # No blank check here: note is NullableText, so "  " is a 422 before the
    # service is entered. apps/core/schemas.py calls that declaration the single
    # source of truth, and a second one here could only ever disagree with it.
    clean_note = note.strip() if note is not None else None
    request = LeaveRequest.objects.create(
        staff=staff,
        leave_type=leave_type,
        start_date=start_date,
        end_date=end_date,
        note=clean_note,
        source=source,
        batch_id=batch_id,
        created_by=actor,
    )
    _create_days(request=request, days=valid, actor=actor)
    return {"request": _request_data(_loaded_request(request.id)), "skipped_days": skipped}


@transaction.atomic
def update_leave_request(  # noqa: PLR0913 -- one complete replacement contract
    *,
    request_id: UUID,
    leave_type_code: str,
    start_date: date,
    end_date: date,
    note: str | None,
    requested_days: list[RequestedDay],
    actor: Staff,
) -> SaveResult:
    """Replace one request's range and projections as a single transaction."""
    request = LeaveRequest.objects.select_for_update().select_related("staff").get(id=request_id)
    leave_type = configured_leave_type(leave_type_code)
    preview = preview_leave(
        staff=request.staff,
        start_date=start_date,
        end_date=end_date,
        exclude_request=request,
    )
    valid, skipped = _validated_days(preview=preview, requested_days=requested_days)
    # No blank check here: note is NullableText, so "  " is a 422 before the
    # service is entered. apps/core/schemas.py calls that declaration the single
    # source of truth, and a second one here could only ever disagree with it.
    clean_note = note.strip() if note is not None else None
    _delete_days(request)
    request.leave_type = leave_type
    request.start_date = start_date
    request.end_date = end_date
    request.note = clean_note
    request.save(update_fields=["leave_type", "start_date", "end_date", "note", "updated_at"])
    _create_days(request=request, days=valid, actor=actor)
    return {"request": _request_data(_loaded_request(request.id)), "skipped_days": skipped}


@transaction.atomic
def delete_leave_request(request_id: UUID) -> None:
    """Delete a request and every generated payroll line."""
    request = LeaveRequest.objects.select_for_update().get(id=request_id)
    _delete_days(request)
    request.delete()


def list_leave_requests(*, scope: Literal["current", "history"], search: str) -> LeaveListData:
    """List current or historical requests with summary figures from the same result set."""
    today = timezone.localdate()
    requests = LeaveRequest.objects.select_related("staff", "leave_type").prefetch_related(
        Prefetch("days", queryset=LeaveDay.objects.order_by("date"))
    )
    requests = (
        requests.filter(end_date__gte=today)
        if scope == "current"
        else requests.filter(end_date__lt=today)
    )
    clean_search = search.strip()
    if clean_search:
        requests = requests.filter(
            Q(staff__first_name__icontains=clean_search)
            | Q(staff__last_name__icontains=clean_search)
            | Q(staff__preferred_name__icontains=clean_search)
            | Q(leave_type__display_name__icontains=clean_search)
        )
    rows = list(requests.order_by("start_date", "staff__last_name", "staff__first_name"))
    away_today = {row.staff_id for row in rows if any(day.date == today for day in row.days.all())}
    return {
        "scope": scope,
        "requests": [_request_data(row) for row in rows],
        "summary": {
            "away_today": len(away_today),
            "upcoming_requests": sum(1 for row in rows if row.start_date > today),
            "upcoming_hours": sum(
                (day.hours for row in rows for day in row.days.all() if day.date >= today),
                Decimal("0"),
            ),
        },
    }


def get_leave_balance(*, staff: Staff, leave_type_code: str) -> LeaveBalanceData:
    """Read the selected mapped balance live from the configured provider."""
    if not staff.xero_user_id:
        raise ValidationError(f"{staff.get_display_full_name()} is not linked to payroll.")
    leave_type = configured_leave_type(leave_type_code)
    job = leave_type.job
    if job is None or job.default_xero_pay_item is None:
        raise ValidationError(f"{leave_type.display_name} is not fully configured.")
    pay_item = job.default_xero_pay_item
    if not pay_item.uses_leave_api:
        raise ValidationError(f"{leave_type.display_name} does not have a leave balance.")
    balances = get_provider().get_payroll_leave_balances(str(staff.xero_user_id))
    for balance in balances:
        if balance.leave_type_external_id == pay_item.xero_id:
            return {"balance": balance.balance, "unit": balance.unit, "name": balance.name}
    raise ValidationError(
        f"Xero returned no {leave_type.display_name} balance for {staff.get_display_full_name()}."
    )


def preview_office_closure(*, start_date: date, end_date: date) -> OfficeClosurePreviewData:
    """Preview public-holiday lines for every staff member active in the range."""
    staff_rows = get_displayable_staff(
        date_range=(start_date, end_date),
        order_by=("last_name", "first_name"),
    )
    previews = [
        preview_leave(staff=staff, start_date=start_date, end_date=end_date) for staff in staff_rows
    ]
    return {
        "start_date": start_date,
        "end_date": end_date,
        "staff": previews,
        "available_staff": sum(1 for row in previews if row["available_hours"] > 0),
        "available_hours": sum((row["available_hours"] for row in previews), Decimal("0")),
    }


@transaction.atomic
def create_office_closure(
    *, start_date: date, end_date: date, note: str | None, actor: Staff
) -> OfficeClosureResult:
    """Create a batched public-holiday request for every affected employee."""
    preview = preview_office_closure(start_date=start_date, end_date=end_date)
    batch_id = uuid.uuid4()
    requests: list[LeaveRequestData] = []
    skipped: list[PreviewDay] = []
    for staff_preview in preview["staff"]:
        requested: list[RequestedDay] = [
            {"date": row["date"], "hours": row["hours"]}
            for row in staff_preview["days"]
            if row["available"]
        ]
        skipped.extend(row for row in staff_preview["days"] if not row["available"])
        if not requested:
            continue
        result = create_leave_request(
            staff_id=UUID(staff_preview["staff_id"]),
            leave_type_code=LeaveType.Code.PUBLIC_HOLIDAY,
            start_date=start_date,
            end_date=end_date,
            note=note,
            requested_days=requested,
            actor=actor,
            source=LeaveRequest.Source.OFFICE_CLOSURE,
            batch_id=batch_id,
        )
        requests.append(result["request"])
        skipped.extend(result["skipped_days"])
    if not requests:
        raise ValidationError("No available office-closure days remain to save.")
    return {"batch_id": str(batch_id), "requests": requests, "skipped_days": skipped}
