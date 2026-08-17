"""Leave-type configuration and provider-neutral payroll mappings."""

from dataclasses import dataclass
from typing import TypedDict
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.accounts.models import Staff
from apps.core.models import CompanyDefaults
from apps.job.models import Job
from apps.timesheet.models import LeaveType


class LeaveTypeData(TypedDict):
    """One fixed leave type as shown on operational and settings screens."""

    code: str
    display_name: str
    job_id: str | None
    job_name: str | None
    xero_pay_item_id: str | None
    xero_pay_item_name: str | None
    expects_leave_api: bool
    configured: bool


class LeaveSettingsData(TypedDict):
    """The fixed types and special jobs selectable in administration."""

    leave_types: list[LeaveTypeData]
    jobs: list[dict[str, str]]


@dataclass(frozen=True, slots=True)
class EmployeeLeaveMapping:
    """A configured Docketworks leave code reduced to what employee setup needs."""

    code: str
    display_name: str
    external_id: str
    standard_entitlement: bool


def leave_type_data(leave_type: LeaveType) -> LeaveTypeData:
    """Shape one configuration row without crossing into the integration layer."""
    job = leave_type.job
    pay_item = job.default_xero_pay_item if job is not None else None
    # Read endpoints must never rely on SingletonModel.get_solo(), whose
    # fallback creates a row when configuration is absent.
    tenant_id = CompanyDefaults.objects.get().xero_tenant_id
    configured = (
        job is not None
        and pay_item is not None
        and bool(pay_item.xero_id)
        and pay_item.xero_tenant_id == tenant_id
        and pay_item.uses_leave_api == leave_type.expects_leave_api
    )
    return {
        "code": leave_type.code,
        "display_name": leave_type.display_name,
        "job_id": str(job.id) if job is not None else None,
        "job_name": job.name if job is not None else None,
        "xero_pay_item_id": str(pay_item.id) if pay_item is not None else None,
        "xero_pay_item_name": pay_item.name if pay_item is not None else None,
        "expects_leave_api": leave_type.expects_leave_api,
        "configured": configured,
    }


def get_leave_settings() -> LeaveSettingsData:
    """Return current fixed-type configuration and eligible local jobs."""
    leave_types = list(
        LeaveType.objects.select_related("job__default_xero_pay_item").order_by("display_name")
    )
    jobs = Job.objects.filter(status="special").order_by("name")
    return {
        "leave_types": [leave_type_data(item) for item in leave_types],
        "jobs": [{"id": str(job.id), "name": job.name} for job in jobs],
    }


@transaction.atomic
def update_leave_type(
    *, code: str, display_name: str, job_id: UUID, xero_pay_item_id: UUID, actor: Staff
) -> LeaveTypeData:
    """Update the displayed type and its one canonical Job-to-pay-item mapping."""
    clean_name = display_name.strip()
    if not clean_name:
        raise ValidationError("display_name must not be blank.")

    leave_type = LeaveType.objects.select_for_update().get(code=code)
    job = Job.objects.select_for_update().get(id=job_id)
    if job.status != "special":
        raise ValidationError("Leave types must use a special Docketworks job.")

    job.default_xero_pay_item_id = xero_pay_item_id
    pay_item = job.default_xero_pay_item
    if not pay_item.xero_id:
        raise ValidationError("The Xero payroll item is not linked to the current organisation.")
    tenant_id = CompanyDefaults.get_solo().xero_tenant_id
    if pay_item.xero_tenant_id != tenant_id:
        raise ValidationError("The Xero payroll item belongs to a different organisation.")
    if pay_item.uses_leave_api != leave_type.expects_leave_api:
        expected = "leave type" if leave_type.expects_leave_api else "earnings rate"
        raise ValidationError(f"{leave_type.display_name} requires a Xero {expected}.")

    job.save(staff=actor, update_fields=["default_xero_pay_item", "updated_at"])
    leave_type.display_name = clean_name
    leave_type.job = job
    leave_type.full_clean()
    leave_type.save(update_fields=["display_name", "job", "updated_at"])
    return leave_type_data(leave_type)


def configured_leave_type(code: str) -> LeaveType:
    """Return one booking-ready type or fail with its configuration defect."""
    leave_type = LeaveType.objects.select_related("job__default_xero_pay_item").get(code=code)
    if not leave_type_data(leave_type)["configured"]:
        raise ValidationError(f"{leave_type.display_name} is not fully configured.")
    return leave_type


def employee_leave_mappings() -> list[EmployeeLeaveMapping]:
    """Return all four configured Leave-API mappings for Xero employee setup."""
    rows = LeaveType.objects.exclude(code=LeaveType.Code.PUBLIC_HOLIDAY).select_related(
        "job__default_xero_pay_item"
    )
    tenant_id = CompanyDefaults.get_solo().xero_tenant_id
    mappings: list[EmployeeLeaveMapping] = []
    for row in rows:
        job = row.job
        pay_item = job.default_xero_pay_item if job is not None else None
        if (
            job is None
            or pay_item is None
            or not pay_item.xero_id
            or pay_item.xero_tenant_id != tenant_id
            or not pay_item.uses_leave_api
        ):
            raise ValueError(
                f"Docketworks leave type {row.display_name} is not linked to a Xero leave type."
            )
        mappings.append(
            EmployeeLeaveMapping(
                code=row.code,
                display_name=row.display_name,
                external_id=str(pay_item.xero_id),
                standard_entitlement=row.code in {LeaveType.Code.ANNUAL, LeaveType.Code.SICK},
            )
        )
    if len(mappings) != 4:
        raise ValueError("All four Docketworks payroll leave types must be configured.")
    return mappings
