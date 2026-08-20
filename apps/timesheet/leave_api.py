"""Superuser-only leave management and configuration endpoints."""

from typing import Literal
from uuid import UUID

from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from ninja import Router
from ninja.errors import HttpError
from ninja.responses import Status

from apps.accounts.models import Staff
from apps.core.auth import SuperuserCookieJWTAuth
from apps.job.models import Job
from apps.timesheet.api import authenticated_staff
from apps.timesheet.leave_schemas import (
    LeaveBalanceOut,
    LeaveListOut,
    LeavePreviewOut,
    LeavePreviewRequest,
    LeaveRequestUpdate,
    LeaveRequestWrite,
    LeaveSaveOut,
    LeaveSettingsOut,
    LeaveSettingsUpdate,
    OfficeClosureOut,
    OfficeClosurePreviewOut,
    OfficeClosureWrite,
)
from apps.timesheet.models import LeaveRequest, LeaveType
from apps.timesheet.services import leave_service, leave_settings

router = Router(auth=SuperuserCookieJWTAuth(), tags=["leave"])


def _validation_message(exc: DjangoValidationError) -> str:
    return "; ".join(exc.messages)


def _requested_days(
    payload: LeaveRequestWrite | LeaveRequestUpdate,
) -> list[leave_service.RequestedDay]:
    return [{"date": row.date, "hours": row.hours} for row in payload.days]


@router.get(
    "/timesheets/leave/requests/",
    operation_id="timesheets_leave_requests_list",
    response=LeaveListOut,
)
def list_requests(
    request: HttpRequest,  # noqa: ARG001
    scope: Literal["current", "history"] = "current",
    search: str = "",
) -> leave_service.LeaveListData:
    """List current or historical leave with filtered summary figures."""
    return leave_service.list_leave_requests(scope=scope, search=search)


@router.post(
    "/timesheets/leave/preview/",
    operation_id="timesheets_leave_preview_create",
    response=LeavePreviewOut,
)
def preview_leave_endpoint(
    request: HttpRequest,  # noqa: ARG001
    payload: LeavePreviewRequest,
) -> leave_service.PreviewData:
    """Preview one employee's scheduled and conflicting dates."""
    staff = get_object_or_404(Staff, id=payload.staff_id)
    try:
        return leave_service.preview_leave(
            staff=staff, start_date=payload.start_date, end_date=payload.end_date
        )
    except DjangoValidationError as exc:
        raise HttpError(400, _validation_message(exc)) from exc


@router.post(
    "/timesheets/leave/requests/",
    operation_id="timesheets_leave_requests_create",
    response=LeaveSaveOut,
)
def create_request(request: HttpRequest, payload: LeaveRequestWrite) -> leave_service.SaveResult:
    """Create a leave request and daily payroll lines."""
    try:
        return leave_service.create_leave_request(
            staff_id=payload.staff_id,
            leave_type_code=payload.leave_type_code,
            start_date=payload.start_date,
            end_date=payload.end_date,
            note=payload.note,
            requested_days=_requested_days(payload),
            actor=authenticated_staff(request),
        )
    except Staff.DoesNotExist as exc:
        raise HttpError(404, "Employee not found.") from exc
    except LeaveType.DoesNotExist as exc:
        raise HttpError(400, "Unknown leave type.") from exc
    except DjangoValidationError as exc:
        raise HttpError(400, _validation_message(exc)) from exc


@router.patch(
    "/timesheets/leave/requests/{uuid:request_id}/",
    operation_id="timesheets_leave_requests_update",
    response=LeaveSaveOut,
)
def update_request(
    request: HttpRequest, request_id: UUID, payload: LeaveRequestUpdate
) -> leave_service.SaveResult:
    """Replace an existing request and its daily payroll lines."""
    try:
        return leave_service.update_leave_request(
            request_id=request_id,
            leave_type_code=payload.leave_type_code,
            start_date=payload.start_date,
            end_date=payload.end_date,
            note=payload.note,
            requested_days=_requested_days(payload),
            actor=authenticated_staff(request),
        )
    except LeaveRequest.DoesNotExist as exc:
        raise HttpError(404, "Leave request not found.") from exc
    except LeaveType.DoesNotExist as exc:
        raise HttpError(400, "Unknown leave type.") from exc
    except DjangoValidationError as exc:
        raise HttpError(400, _validation_message(exc)) from exc


@router.delete(
    "/timesheets/leave/requests/{uuid:request_id}/",
    operation_id="timesheets_leave_requests_delete",
    response={204: None},
)
def delete_request(request: HttpRequest, request_id: UUID) -> Status[None]:  # noqa: ARG001
    """Cancel leave and remove its daily payroll lines."""
    try:
        leave_service.delete_leave_request(request_id)
    except LeaveRequest.DoesNotExist as exc:
        raise HttpError(404, "Leave request not found.") from exc
    return Status(204, None)


@router.get(
    "/timesheets/leave/balance/",
    operation_id="timesheets_leave_balance_retrieve",
    response=LeaveBalanceOut,
)
def leave_balance(
    request: HttpRequest,  # noqa: ARG001
    staff_id: UUID,
    leave_type_code: str,
) -> leave_service.LeaveBalanceData:
    """Read the employee's selected balance live from payroll."""
    staff = get_object_or_404(Staff, id=staff_id)
    try:
        return leave_service.get_leave_balance(staff=staff, leave_type_code=leave_type_code)
    except LeaveType.DoesNotExist as exc:
        raise HttpError(400, "Unknown leave type.") from exc
    except DjangoValidationError as exc:
        raise HttpError(400, _validation_message(exc)) from exc


@router.post(
    "/timesheets/leave/office-closure/preview/",
    operation_id="timesheets_leave_office_closure_preview_create",
    response=OfficeClosurePreviewOut,
)
def preview_office_closure_endpoint(
    request: HttpRequest,  # noqa: ARG001
    payload: OfficeClosureWrite,
) -> leave_service.OfficeClosurePreviewData:
    """Preview the active scheduled staff affected by a closure."""
    try:
        return leave_service.preview_office_closure(
            start_date=payload.start_date, end_date=payload.end_date
        )
    except DjangoValidationError as exc:
        raise HttpError(400, _validation_message(exc)) from exc


@router.post(
    "/timesheets/leave/office-closure/",
    operation_id="timesheets_leave_office_closure_create",
    response=OfficeClosureOut,
)
def create_office_closure_endpoint(
    request: HttpRequest, payload: OfficeClosureWrite
) -> leave_service.OfficeClosureResult:
    """Create Public Holiday leave for all affected staff."""
    try:
        return leave_service.create_office_closure(
            start_date=payload.start_date,
            end_date=payload.end_date,
            note=payload.note,
            actor=authenticated_staff(request),
        )
    # No LeaveType.DoesNotExist arm: the code passed down is the constant
    # PUBLIC_HOLIDAY and all five rows are seeded by migration, so an
    # unconfigured type raises ValidationError from leave_settings instead and
    # lands below. The row would have to be deleted for that arm to run.
    except DjangoValidationError as exc:
        raise HttpError(400, _validation_message(exc)) from exc


@router.get(
    "/timesheets/leave-settings/",
    operation_id="timesheets_leave_settings_retrieve",
    response=LeaveSettingsOut,
)
def get_settings(request: HttpRequest) -> leave_settings.LeaveSettingsData:  # noqa: ARG001
    """Return the fixed types and their editable mappings."""
    return leave_settings.get_leave_settings()


@router.patch(
    "/timesheets/leave-settings/",
    operation_id="timesheets_leave_settings_update",
    response=LeaveSettingsOut,
)
def update_settings(
    request: HttpRequest, payload: LeaveSettingsUpdate
) -> leave_settings.LeaveSettingsData:
    """Save every changed leave mapping, or none of them."""
    updates = [
        leave_settings.LeaveTypeUpdateData(
            code=row.code,
            display_name=row.display_name,
            job_id=row.job_id,
            xero_pay_item_id=row.xero_pay_item_id,
        )
        for row in payload.leave_types
    ]
    try:
        return leave_settings.update_leave_types(
            updates=updates, actor=authenticated_staff(request)
        )
    except LeaveType.DoesNotExist as exc:
        raise HttpError(404, "Leave type not found.") from exc
    except Job.DoesNotExist as exc:
        raise HttpError(400, "Docketworks Job not found.") from exc
    except DjangoValidationError as exc:
        raise HttpError(400, _validation_message(exc)) from exc
