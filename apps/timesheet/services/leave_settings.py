"""Leave-type configuration and provider-neutral payroll mappings."""

from dataclasses import dataclass
from typing import TypedDict
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.accounts.models import Staff
from apps.core.models import CompanyDefaults
from apps.job.models import Job
from apps.timesheet.leave_schemas import PostingSurfaceOut
from apps.timesheet.models import LeaveType, PostingSurface


class LeaveTypeData(TypedDict):
    """One fixed leave type as shown on operational and settings screens."""

    code: str
    display_name: str
    job_id: str | None
    job_name: str | None
    xero_pay_item_id: str | None
    xero_pay_item_name: str | None
    posting_surface: PostingSurfaceOut
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
    #: None is the only valid value for the xero_computed surface, and invalid
    #: for every other; _apply_leave_type_update refuses both mismatches.
    xero_pay_item_id: UUID | None


@dataclass(frozen=True, slots=True)
class EmployeeLeaveMapping:
    """A configured Docketworks leave code reduced to what employee setup needs."""

    code: str
    display_name: str
    external_id: str
    standard_entitlement: bool


def _surface_out(surface: PostingSurface) -> PostingSurfaceOut:
    """Convert the enum to its wire twin, spelled out so mypy proves the mapping total.

    ``surface.value`` says the same thing at runtime, but its static type is
    ``str``, and a widened wire field is exactly what PostingSurfaceOut exists
    to prevent (ADR 0028).
    """
    match surface:
        case PostingSurface.TIMESHEET:
            return "timesheet"
        case PostingSurface.LEAVE_API:
            return "leave_api"
        case PostingSurface.XERO_COMPUTED:
            return "xero_computed"


def leave_type_data(leave_type: LeaveType) -> LeaveTypeData:
    """Shape one configuration row without crossing into the integration layer."""
    job = leave_type.job
    if leave_type.posting_surface is PostingSurface.XERO_COMPUTED:
        # Fable: This surface has no Xero object at all — the row is identified
        # by its Job FK and posts nothing (ADR 0007). The job's NOT NULL
        # default pay item (auto-refilled with Ordinary Time) is inert here,
        # and serving it put a pay item on the wire that the update contract
        # then had to refuse: the row read as carrying a value it may not have.
        pay_item = None
        configured = job is not None
    else:
        pay_item = job.default_xero_pay_item if job is not None else None
        tenant_id = CompanyDefaults.get_solo().xero_tenant_id
        configured = (
            job is not None
            and pay_item is not None
            and bool(pay_item.xero_id)
            and pay_item.xero_tenant_id == tenant_id
            and pay_item.uses_leave_api == (leave_type.posting_surface is PostingSurface.LEAVE_API)
        )
    return {
        "code": leave_type.code,
        "display_name": leave_type.display_name,
        "job_id": str(job.id) if job is not None else None,
        "job_name": job.name if job is not None else None,
        "xero_pay_item_id": str(pay_item.id) if pay_item is not None else None,
        "xero_pay_item_name": pay_item.name if pay_item is not None else None,
        "posting_surface": _surface_out(leave_type.posting_surface),
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


def _refuse_shared_pay_item(update: LeaveTypeUpdateData) -> None:
    """Refuse two categories claiming one Xero leave type.

    Opus: The classifier indexes categories BY pay item, so a shared one resolves
    to whichever row sorts first — every Annual Leave line would then report and
    reconcile as the other category. The name-based lookup this replaced was
    immune to the collision by accident; keying on the pay item makes it a real
    state, so it is refused rather than silently resolved (ADR 0015).
    """
    if update.xero_pay_item_id is None:
        return
    clash = (
        LeaveType.objects.filter(job__default_xero_pay_item_id=update.xero_pay_item_id)
        .exclude(code=update.code)
        .first()
    )
    if clash is not None:
        raise ValidationError(f"{clash.display_name} already uses that Xero leave type.")


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

    _refuse_shared_pay_item(update)

    if leave_type.posting_surface is PostingSurface.XERO_COMPUTED:
        # Opus: Xero pays this day from its own calculation, so there is no Xero
        # object to name and offering one would post the day a second time.
        #
        # The job's own default is deliberately left alone: it is a NOT NULL
        # column that ``Job.save`` re-fills with Ordinary Time, so clearing it
        # here only looked like it worked. Nothing routes on it — the classifier
        # indexes pay items for Leave-API categories only, and ``CostLine.clean``
        # refuses a pay item on these lines — so the stale dropdown default is
        # inert rather than load-bearing.
        if update.xero_pay_item_id is not None:
            raise ValidationError(
                f"{leave_type.display_name} is paid by Xero's own calculation and takes no "
                "Xero payroll item."
            )
    else:
        # Refused before assignment: default_xero_pay_item is a NOT NULL
        # column, so a null id would raise RelatedObjectDoesNotExist on the
        # read below instead of producing a nameable refusal.
        if update.xero_pay_item_id is None:
            raise ValidationError(f"{leave_type.display_name} requires a Xero leave type.")
        job.default_xero_pay_item_id = update.xero_pay_item_id
        pay_item = job.default_xero_pay_item
        if not pay_item.xero_id:
            raise ValidationError(
                "The Xero payroll item is not linked to the current organisation."
            )
        tenant_id = CompanyDefaults.get_solo().xero_tenant_id
        if pay_item.xero_tenant_id != tenant_id:
            raise ValidationError("The Xero payroll item belongs to a different organisation.")
        if not pay_item.uses_leave_api:
            raise ValidationError(f"{leave_type.display_name} requires a Xero leave type.")

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


#: Opus: The categories Xero assigns to an employee, derived from the surface
#: rather than by excluding public holiday by name: a category Xero pays from
#: its own calculation has no leave type to assign, and deriving it means the
#: count below cannot disagree with the classifier.
LEAVE_API_CODES = tuple(
    code for code in LeaveType.Code if LeaveType.surface_for(code) is PostingSurface.LEAVE_API
)


def employee_leave_mappings() -> list[EmployeeLeaveMapping]:
    """Return every configured Leave-API mapping for Xero employee setup."""
    rows = LeaveType.objects.filter(code__in=LEAVE_API_CODES).select_related(
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
    if len(mappings) != len(LEAVE_API_CODES):
        raise ValueError(
            f"All {len(LEAVE_API_CODES)} Docketworks payroll leave types must be configured."
        )
    return mappings
