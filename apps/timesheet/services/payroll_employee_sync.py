"""Linking ``Staff`` rows with payroll employees in the connected organisation.

The restore path's problem, and why this module exists: a database restored
from production carries a ``xero_user_id`` on every staff member who was
linked in production, and every one of those ids names an employee the
non-production organisation has never held. Left alone the mirror looks
linked and can pay nobody.

``sync_staff`` re-links them. It matches by the Staff UUID stamped into the
Xero job title first — the only key that survives a restore intact — then by
email, then by name, and creates the employee when nothing matches. Each
linked row is stamped with the organisation it was linked to, which is what
lets the seed measure whether it has finished (``apps/xero/seeding.py``).

Xero is reached through ``AccountingProvider``: apps.xero sits above the
domain apps in the import contract, so this module cannot call it directly.

Normal Xero-to-Docketworks employee import belongs to the generic Xero entity
sync. This module now serves only the non-production seed path.
"""

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal
from typing import TYPE_CHECKING, TypedDict

from django.db import transaction

from apps.accounting.registry import get_provider
from apps.accounting.types import (
    NewPayrollEmployee,
    PayrollAddress,
    PayrollEmployeeRef,
)
from apps.accounts.models import Staff
from apps.core.models import CompanyDefaults
from apps.timesheet.services.demo_payroll_data import generate_ird_number, get_bank_account

if TYPE_CHECKING:
    from django.db.models import QuerySet

logger = logging.getLogger("timesheet.payroll")

# Store the Staff UUID in the Xero job title ("Workshop Worker [uuid]") so a
# restored database can be re-linked without relying on mutable email or name.
STAFF_UUID_PATTERN = re.compile(r"\[([0-9a-f-]{36})\]$", re.IGNORECASE)

DEFAULT_JOB_TITLE = "Workshop Worker"

# A created demo employee needs a date of birth the payroll product will accept.
DEFAULT_DATE_OF_BIRTH = date(1990, 1, 1)

# Xero does NOT persist Employee.end_date on create — a departed staff member
# is created as an ACTIVE employee, verified against the live demo
# organisation. NZ payroll exposes no termination endpoint (the SDK offers
# create_employment and nothing to reverse it), so there is no second call that
# would fix it. Accepted rather than worked around: an active employee can be
# paid for the historical weeks a restore exists to exercise, and a terminated
# one could not.

WEEKDAY_NAMES = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)


@dataclass(frozen=True, slots=True)
class EmployeeRecord:
    """A payroll employee reduced to the fields matching needs."""

    employee_id: str
    first_name: str
    last_name: str
    email: str | None
    staff_id: str | None


@dataclass(frozen=True, slots=True)
class EmployeeIndex:
    """Payroll employees indexed by every key the matcher tries, in priority order."""

    by_staff_id: dict[str, EmployeeRecord]
    by_email: dict[str, EmployeeRecord]
    by_name: dict[tuple[str, str], EmployeeRecord]


class StaffSummary(TypedDict):
    """Data contract for StaffSummary."""

    staff_id: str
    office_email: str
    first_name: str
    last_name: str


class LinkSummary(StaffSummary):
    """Data contract for LinkSummary."""

    xero_employee_id: str | None
    xero_email: str | None
    xero_name: str | None


@dataclass(frozen=True)
class SyncStaffResult:
    """What one ``sync_staff`` run did, per staff member.

    A dataclass rather than v1's dict of lists: every caller reads these four
    buckets by name to build its report, and a typo'd key silently reported
    zero (ADR 0028).
    """

    linked: list[LinkSummary] = field(default_factory=list)
    created: list[LinkSummary] = field(default_factory=list)
    already_linked: list[StaffSummary] = field(default_factory=list)
    unmatched: list[StaffSummary] = field(default_factory=list)


class StaffNotPayrollReadyError(ValueError):
    """Staff rows cannot be created as payroll employees, named all at once.

    Raised before the first write. v1 raised on the first offending row, which
    on a real dataset meant discovering the second one only after a further
    round trip per employee already created — and this runs unattended on
    server instances, where nobody is there to restart it.
    """


def clean_string(value: str | None, max_length: int | None = None) -> str | None:
    """Strip and truncate a value; empty becomes None."""
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    if max_length is not None:
        return cleaned[:max_length]
    return cleaned


def serialize_employee(employee: PayrollEmployeeRef) -> EmployeeRecord:
    """Reduce a provider employee to its matchable identity."""
    match = STAFF_UUID_PATTERN.search(employee.job_title or "")
    email = (employee.email or "").strip().lower()
    return EmployeeRecord(
        employee_id=employee.external_id,
        first_name=employee.first_name.strip(),
        last_name=employee.last_name.strip(),
        email=email or None,
        staff_id=match.group(1).lower() if match else None,
    )


def index_employees(employees: Sequence[PayrollEmployeeRef]) -> EmployeeIndex:
    """Index payroll employees by staff id, email and name (v1 ``_index_xero_employees``).

    First record wins on each key, so a duplicate never displaces the original.

    A nameless employee is left out of the name index. Xero's demo
    organisation ships stub employees with fields we would not accept from a
    real one, and v1 indexed them under ``("", "")`` — which any Staff row
    with a blank name then matched, adopting a stub employee instead of
    getting one of its own.
    """
    by_staff_id: dict[str, EmployeeRecord] = {}
    by_email: dict[str, EmployeeRecord] = {}
    by_name: dict[tuple[str, str], EmployeeRecord] = {}

    for employee in employees:
        record = serialize_employee(employee)
        if record.staff_id:
            by_staff_id.setdefault(record.staff_id, record)
        if record.email:
            by_email.setdefault(record.email, record)
        if record.first_name or record.last_name:
            by_name.setdefault((record.first_name.lower(), record.last_name.lower()), record)

    return EmployeeIndex(by_staff_id=by_staff_id, by_email=by_email, by_name=by_name)


def match_staff_to_employee(staff: Staff, index: EmployeeIndex) -> EmployeeRecord | None:
    """Find the payroll employee for a Staff row (v1 priority: UUID, email, name).

    The UUID in the job title is checked first because it is the only key
    that survives a database restore intact.
    """
    staff_id = str(staff.id).lower()
    if staff_id in index.by_staff_id:
        return index.by_staff_id[staff_id]

    email = staff.office_email.strip().lower()
    if email and email in index.by_email:
        return index.by_email[email]

    first = staff.first_name.strip().lower()
    last = staff.last_name.strip().lower()
    if not first and not last:
        return None
    return index.by_name.get((first, last))


def staff_summary(staff: Staff) -> StaffSummary:
    """Build the staff identity block of a sync summary."""
    return {
        "staff_id": str(staff.id),
        "office_email": staff.office_email,
        "first_name": staff.first_name,
        "last_name": staff.last_name,
    }


def link_summary(
    staff: Staff, employee_id: str | None, match: EmployeeRecord | None
) -> LinkSummary:
    """One row of a sync summary: staff identity plus the matched employee."""
    xero_name = f"{match.first_name} {match.last_name}".strip() if match else None
    return {
        **staff_summary(staff),
        "xero_employee_id": employee_id,
        "xero_email": match.email if match else None,
        "xero_name": xero_name,
    }


def xero_job_title(staff: Staff) -> str:
    """Build the job title carrying the Staff UUID for reliable re-linking."""
    return f"{DEFAULT_JOB_TITLE} [{staff.id}]"


def hours_per_week(staff: Staff) -> dict[str, float]:
    """Read a staff member's contracted hours per weekday."""
    hours = (
        staff.hours_mon,
        staff.hours_tue,
        staff.hours_wed,
        staff.hours_thu,
        staff.hours_fri,
        staff.hours_sat,
        staff.hours_sun,
    )
    missing = [name for name, value in zip(WEEKDAY_NAMES, hours, strict=True) if value is None]
    if missing:
        raise ValueError(
            f"Staff {staff.id} ({staff.office_email}) missing hours for: {', '.join(missing)}"
        )
    return {name: float(value) for name, value in zip(WEEKDAY_NAMES, hours, strict=True)}


def _hours_between(start: time | None, end: time | None) -> float:
    """Hours between two times on the same day, never negative."""
    if start is None or end is None:
        return 0.0
    anchor = datetime(2000, 1, 1)  # noqa: DTZ001 -- date-free duration arithmetic
    delta = datetime.combine(anchor, end) - datetime.combine(anchor, start)
    return max(delta.total_seconds() / 3600, 0.0)


def default_working_hours() -> dict[str, float]:
    """Company working hours, used when the organisation holds no working pattern."""
    company = CompanyDefaults.get_solo()
    return {
        "monday": _hours_between(company.mon_start, company.mon_end),
        "tuesday": _hours_between(company.tue_start, company.tue_end),
        "wednesday": _hours_between(company.wed_start, company.wed_end),
        "thursday": _hours_between(company.thu_start, company.thu_end),
        "friday": _hours_between(company.fri_start, company.fri_end),
        "saturday": 0.0,
        "sunday": 0.0,
    }


def link_staff(staff: Staff, employee_id: str, tenant_id: str) -> None:
    """Record which organisation's payroll employee this Staff row is.

    Both columns together: an id without the organisation it belongs to is
    exactly the state a restored production dump arrives in, and it is what
    made a fully-unlinked mirror read as linked.
    """
    logger.info(
        "Linking staff %s (%s) to payroll employee %s in %s",
        staff.id,
        staff.office_email,
        employee_id,
        tenant_id,
    )
    staff.xero_user_id = employee_id
    staff.xero_tenant_id = tenant_id
    with transaction.atomic():
        staff.save(update_fields=["xero_user_id", "xero_tenant_id", "updated_at"])


def syncable_staff() -> list[Staff]:
    """List current staff with a wage rate — the onboarding selection."""
    return list(Staff.objects.filter(date_left__isnull=True, wage_rate__gt=Decimal("0")))


def staff_needing_payroll_link(tenant_id: str) -> "QuerySet[Staff]":
    """Staff carrying an employee id that does not belong to this organisation.

    This is the restore selection, and it deliberately includes staff who have
    left: they were linked in production, historical timesheets may still need
    posting for them, and the organisation should hold their employment
    history with an end date. Staff who carried no id in the dump were never
    linked in production and are left alone.

    ``.exclude()`` on a nullable column keeps NULL rows, which is what makes
    this fire on a fresh restore: the production ids are present and the
    tenant column is NULL, so nothing attributes them to this organisation.
    """
    return Staff.objects.filter(xero_user_id__isnull=False).exclude(xero_tenant_id=tenant_id)


def staff_needing_seed(tenant_id: str) -> list[Staff]:
    """Staff the seed must create or re-link in this non-production organisation."""
    candidates = {
        staff.pk: staff for staff in [*syncable_staff(), *staff_needing_payroll_link(tenant_id)]
    }
    return [
        staff
        for staff in candidates.values()
        if not staff.xero_user_id or staff.xero_tenant_id != tenant_id
    ]


def _required_address_field(value: str | None, name: str) -> str:
    """Return an employer address field, refusing the NULL the model allows.

    One field at a time rather than the name-them-all shape the staff batch
    uses: there is exactly one CompanyDefaults row, so an operator fixes every
    missing field on one screen, and a second "which are missing" sweep would
    be a copy of this predicate free to disagree with it.
    """
    if not value:
        raise StaffNotPayrollReadyError(
            f"CompanyDefaults.{name} is not set, and a payroll employee cannot be "
            "created without a full employer address."
        )
    return value


def _company_address() -> PayrollAddress:
    """Read the employer address every created payroll employee is registered at."""
    company = CompanyDefaults.get_solo()
    return PayrollAddress(
        address_line1=_required_address_field(company.address_line1, "address_line1"),
        address_line2=company.address_line2,
        suburb=company.suburb,
        city=_required_address_field(company.city, "city"),
        post_code=_required_address_field(company.post_code, "post_code"),
        country_name=_required_address_field(company.country, "country"),
    )


def _creation_refusals(staff: Staff) -> list[str]:
    """Everything about this Staff row that blocks creating a payroll employee."""
    refusals: list[str] = []
    if not clean_string(staff.first_name) or not clean_string(staff.last_name):
        refusals.append("missing first or last name")
    if not clean_string(staff.office_email):
        refusals.append("missing email")
    if staff.base_wage_rate <= Decimal("0"):
        refusals.append(f"base_wage_rate is {staff.base_wage_rate}")
    try:
        hours = hours_per_week(staff)
    # deliberate-swallow: this function's whole job is to turn "why can this row
    # not be created" into text, and hours_per_week already answers that by
    # naming the missing weekdays. Re-raising would abandon the batch at the
    # first bad row — exactly the v1 behaviour _assert_creatable exists to
    # replace — and the message is not lost: it reaches the operator inside the
    # StaffNotPayrollReadyError that names every unusable row at once.
    except ValueError as exc:
        refusals.append(str(exc))
    else:
        if not any(value > 0 for value in hours.values()):
            refusals.append("no working days (all weekday hours are zero)")
    return refusals


def _assert_creatable(staff_members: Sequence[Staff]) -> None:
    """Refuse the whole batch, naming every unusable row, before any write."""
    problems = [
        f"  {staff.office_email}: {'; '.join(refusals)}"
        for staff in staff_members
        if (refusals := _creation_refusals(staff))
    ]
    if problems:
        raise StaffNotPayrollReadyError(
            f"{len(problems)} of {len(staff_members)} staff cannot be created as payroll "
            "employees. Fix the data, not the reader (ADR 0015):\n" + "\n".join(problems)
        )


def _employee_spec(
    staff: Staff, address: PayrollAddress, batch_position: int
) -> NewPayrollEmployee:
    """Build the creation spec for one staff member.

    ``batch_position`` is 1-based and only feeds the fake IRD/bank generators,
    which need distinct values within the organisation being seeded.
    """
    first_name = clean_string(staff.first_name, 35)
    last_name = clean_string(staff.last_name, 35)
    email = clean_string(staff.office_email, 255)
    if first_name is None or last_name is None or email is None:
        raise StaffNotPayrollReadyError(f"Staff {staff.id} has no usable name or email")

    return NewPayrollEmployee(
        staff_id=staff.id,
        first_name=first_name,
        last_name=last_name,
        email=email,
        job_title=xero_job_title(staff),
        date_of_birth=DEFAULT_DATE_OF_BIRTH,
        start_date=staff.employment_start_date,
        end_date=staff.date_left,
        address=address,
        hours_per_week=hours_per_week(staff),
        hourly_rate=staff.base_wage_rate,
        ird_number=generate_ird_number(batch_position),
        bank_account_number=get_bank_account(batch_position),
    )


def _partition(
    staff_members: Sequence[Staff], index: EmployeeIndex, tenant_id: str
) -> tuple[list[StaffSummary], list[tuple[Staff, EmployeeRecord]], list[Staff]]:
    """Split the batch into already-linked, matched, and unmatched.

    Two staff rows matching the SAME employee is refused rather than resolved:
    ``Staff.xero_user_id`` is unique, so one of the two saves would fail
    partway through the batch, and which one is an accident of ordering.
    """
    already_linked: list[StaffSummary] = []
    matched: list[tuple[Staff, EmployeeRecord]] = []
    unmatched: list[Staff] = []
    claimed: dict[str, Staff] = {}

    for staff in staff_members:
        if staff.xero_user_id and staff.xero_tenant_id == tenant_id:
            already_linked.append(staff_summary(staff))
            continue

        match = match_staff_to_employee(staff, index)
        if match is None:
            unmatched.append(staff)
            continue

        previous = claimed.get(match.employee_id)
        if previous is not None:
            raise StaffNotPayrollReadyError(
                f"Staff {previous.office_email} and {staff.office_email} both match "
                "payroll employee "
                f"{match.employee_id} ({match.first_name} {match.last_name}). Give one of "
                "them a distinct name or email, or stamp the intended Staff UUID into the "
                "employee's job title in the payroll organisation, then re-run."
            )
        claimed[match.employee_id] = staff
        matched.append((staff, match))

    return already_linked, matched, unmatched


def sync_staff(
    staff_members: Sequence[Staff] | None = None,
    *,
    tenant_id: str,
    dry_run: bool = False,
    allow_create: bool = False,
) -> SyncStaffResult:
    """Link Staff rows to payroll employees, optionally creating the missing ones.

    ``tenant_id`` is passed in rather than looked up: this module sits below
    the integration in the import contract and has no way to ask which
    organisation is connected, and the value is what gets stamped onto every
    row it links.
    """
    if staff_members is None:
        staff_members = syncable_staff()
    if not staff_members:
        return SyncStaffResult()

    provider = get_provider()
    index = index_employees(provider.list_payroll_employees())
    already_linked, matched, unmatched = _partition(staff_members, index, tenant_id)

    to_create = unmatched if allow_create else []
    if to_create:
        # Only the rows that will actually be created are validated: a matched
        # row is linked to an employee the organisation already holds and
        # needs none of the creation fields.
        _assert_creatable(to_create)

    if dry_run:
        return SyncStaffResult(
            linked=[link_summary(staff, match.employee_id, match) for staff, match in matched],
            created=[link_summary(staff, None, None) for staff in to_create],
            already_linked=already_linked,
            unmatched=[staff_summary(staff) for staff in unmatched if not allow_create],
        )

    result = SyncStaffResult(already_linked=already_linked)

    for staff, match in matched:
        # v1's order: push the local name up first, then record the link. A
        # link recorded before a failing rename would claim an employee still
        # carrying the previous organisation's name.
        provider.update_payroll_employee_name(match.employee_id, staff.first_name, staff.last_name)
        link_staff(staff, match.employee_id, tenant_id)
        result.linked.append(link_summary(staff, match.employee_id, match))

    if to_create:
        address = _company_address()
        for position, staff in enumerate(to_create, start=1):
            created = provider.create_payroll_employee(_employee_spec(staff, address, position))
            link_staff(staff, created.external_id, tenant_id)
            result.created.append(
                link_summary(staff, created.external_id, serialize_employee(created))
            )
            logger.info(
                "Created payroll employee %d/%d (%s)",
                position,
                len(to_create),
                staff.office_email,
            )

    if not allow_create:
        result.unmatched.extend(staff_summary(staff) for staff in unmatched)

    return result


def active_on(employee_end_date: date | None, today: date) -> bool:
    """Whether a payroll employee is still active on a date."""
    return employee_end_date is None or employee_end_date > today
