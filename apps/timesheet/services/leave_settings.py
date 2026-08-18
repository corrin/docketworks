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
    """The fixed types and their editable mappings."""

    leave_types: list[LeaveTypeData]


@dataclass(frozen=True, slots=True)
class LeaveTypeUpdateData:
    """One row of a settings save, already parsed off the wire."""

    code: str
    display_name: str
    job_id: UUID
    xero_pay_item_id: UUID


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
    tenant_id = CompanyDefaults.get_solo().xero_tenant_id
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
    """Return the current fixed-type configuration."""
    leave_types = list(
        LeaveType.objects.select_related("job__default_xero_pay_item").order_by("display_name")
    )
    return {"leave_types": [leave_type_data(item) for item in leave_types]}


@transaction.atomic
def update_leave_types(*, updates: list[LeaveTypeUpdateData], actor: Staff) -> LeaveSettingsData:
    """Apply every changed mapping as one transaction, or none of them."""
    codes = [update.code for update in updates]
    if len(set(codes)) != len(codes):
        raise ValidationError("Each leave type may be saved once per request.")

    # LeaveType.job is a OneToOne: assigning Job A to Annual while Sick still
    # holds it fails uniqueness even when the submitted set is a valid swap,
    # and a three-way rotation has no valid serial order at all. Detaching the
    # batch first makes that intermediate state invisible outside this
    # transaction — which is why this endpoint takes a list. The rejected
    # alternative, a client loop over per-code PATCHes, cannot express a swap.
    LeaveType.objects.filter(code__in=codes).update(job=None)
    for update in updates:
        _apply_leave_type_update(update=update, actor=actor)
    return get_leave_settings()


def _apply_leave_type_update(*, update: LeaveTypeUpdateData, actor: Staff) -> None:
    """Update one type's displayed name and its canonical Job-to-pay-item mapping."""
    # Both an empty list and a blank display_name are 422s at the schema
    # (LeaveSettingsUpdate.leave_types has min_length=1; display_name carries
    # StringConstraints(min_length=1, strip_whitespace=True)), so re-checking
    # here could only ever drift from the contract clients are validated against.
    clean_name = update.display_name.strip()

    leave_type = LeaveType.objects.select_for_update().get(code=update.code)
    job = Job.objects.select_for_update().get(id=update.job_id)
    if job.status != "special":
        raise ValidationError("Leave types must use a special Docketworks job.")
    # The batch detach above frees only the codes being saved, so a job still
    # held by an untouched type would surface as an IntegrityError rather than
    # a named refusal.
    clash = LeaveType.objects.filter(job_id=job.id).exclude(code=update.code).first()
    if clash is not None:
        raise ValidationError(f"{clash.display_name} already uses that Docketworks job.")

    job.default_xero_pay_item_id = update.xero_pay_item_id
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
