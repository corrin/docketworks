"""Linking ``Staff`` rows with Xero Payroll employees.

Ported from v1 ``apps/timesheet/services/payroll_employee_sync.py``. v1's class
mixed two things: a pure matching engine (index Xero employees, match a Staff
row against them, shape the summaries, read a staff member's working week) and
the Xero API orchestration around it.

Per the phase plan only the non-Xero parts port now. They are module functions
here so they are directly testable without a Xero double; the two orchestration
entry points (``sync_staff``, ``import_staff_from_xero``) are loud Phase 4
seams — the same shape as the accounting-provider seam in
``apps/company/services/company_rest_service.py``.

Also deferred with Phase 4: v1's ``demo_payroll_data`` module (fake IRD numbers
and bank accounts for employee CREATION in a demo tenant). It needs the
``python-stdnum`` dependency and is only reachable from the creation path,
which is itself a seam.
"""

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from typing import Protocol, TypedDict

from django.db import transaction

from apps.accounts.models import Staff
from apps.core.models import CompanyDefaults

logger = logging.getLogger("timesheet.payroll")

# v1 stored the Staff UUID in the Xero job title ("Workshop Worker [uuid]") so
# a restored database can be re-linked without relying on email or name.
STAFF_UUID_PATTERN = re.compile(r"\[([0-9a-f-]{36})\]$", re.IGNORECASE)

DEFAULT_JOB_TITLE = "Workshop Worker"
PHASE_4 = (
    "Xero Payroll integration is not ported yet (Phase 4); "
    "no employee data was read from or written to Xero."
)

WEEKDAY_NAMES = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)


class XeroEmployee(Protocol):
    """The Xero Payroll employee surface the matcher reads."""

    @property
    def employee_id(self) -> object:
        """Xero's employee identifier."""

    @property
    def first_name(self) -> str | None:
        """The employee's first name in Xero."""

    @property
    def last_name(self) -> str | None:
        """The employee's last name in Xero."""

    @property
    def email(self) -> str | None:
        """The employee's email in Xero, if any."""

    @property
    def job_title(self) -> str | None:
        """The Xero job title (carries the Staff UUID)."""


@dataclass(frozen=True, slots=True)
class EmployeeRecord:
    """A Xero employee reduced to the fields matching needs (v1 ``_serialize_employee``)."""

    employee_id: str | None
    first_name: str
    last_name: str
    email: str | None
    staff_id: str | None


@dataclass(frozen=True, slots=True)
class EmployeeIndex:
    """Xero employees indexed by every key the matcher tries, in priority order."""

    by_staff_id: dict[str, EmployeeRecord]
    by_email: dict[str, EmployeeRecord]
    by_name: dict[tuple[str, str], EmployeeRecord]


class StaffSummary(TypedDict):
    """v1 ``_format_staff``: the staff identity in a sync summary."""

    staff_id: str
    email: str
    first_name: str
    last_name: str


class LinkSummary(StaffSummary):
    """v1 ``_summarize_link``: a staff identity plus the Xero side of the link."""

    xero_employee_id: str | None
    xero_email: str | None
    xero_name: str | None


def clean_string(value: str | None, max_length: int | None = None) -> str | None:
    """Strip and truncate a value; empty becomes None (v1 ``_clean_string``)."""
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    if max_length is not None:
        return cleaned[:max_length]
    return cleaned


def serialize_employee(employee: XeroEmployee) -> EmployeeRecord:
    """Reduce a Xero employee to its matchable identity (v1)."""
    job_title = employee.job_title or ""
    match = STAFF_UUID_PATTERN.search(job_title)
    email = (employee.email or "").strip().lower()
    return EmployeeRecord(
        employee_id=str(employee.employee_id) if employee.employee_id else None,
        first_name=(employee.first_name or "").strip(),
        last_name=(employee.last_name or "").strip(),
        email=email or None,
        staff_id=match.group(1).lower() if match else None,
    )


def index_employees(employees: list[XeroEmployee]) -> EmployeeIndex:
    """Index Xero employees by staff id, email and name (v1 ``_index_xero_employees``).

    First record wins on each key, so a duplicate never displaces the original.
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
        by_name.setdefault((record.first_name.lower(), record.last_name.lower()), record)

    return EmployeeIndex(by_staff_id=by_staff_id, by_email=by_email, by_name=by_name)


def match_staff_to_employee(staff: Staff, index: EmployeeIndex) -> EmployeeRecord | None:
    """Find the Xero employee for a Staff row (v1 priority: UUID, email, name).

    The UUID in the Xero job title is checked first because it is the only key
    that survives a database restore intact.
    """
    staff_id = str(staff.id).lower()
    if staff_id in index.by_staff_id:
        return index.by_staff_id[staff_id]

    email = staff.email.strip().lower()
    if email and email in index.by_email:
        return index.by_email[email]

    name_key = (staff.first_name.strip().lower(), staff.last_name.strip().lower())
    return index.by_name.get(name_key)


def staff_summary(staff: Staff) -> StaffSummary:
    """Build the staff identity block of a sync summary (v1 ``_format_staff``)."""
    return {
        "staff_id": str(staff.id),
        "email": staff.email,
        "first_name": staff.first_name,
        "last_name": staff.last_name,
    }


def link_summary(
    staff: Staff, employee_id: str | None, match: EmployeeRecord | None
) -> LinkSummary:
    """One row of a sync summary: staff identity plus the matched employee (v1)."""
    xero_name = f"{match.first_name} {match.last_name}".strip() if match else None
    return {
        **staff_summary(staff),
        "xero_employee_id": employee_id,
        "xero_email": match.email if match else None,
        "xero_name": xero_name,
    }


def xero_job_title(staff: Staff) -> str:
    """Build the Xero job title carrying the Staff UUID for reliable re-linking (v1)."""
    return f"{DEFAULT_JOB_TITLE} [{staff.id}]"


def hours_per_week(staff: Staff) -> dict[str, float]:
    """Read a staff member's contracted hours per weekday (v1 ``_get_hours_per_week``)."""
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
            f"Staff {staff.id} ({staff.email}) missing hours for: {', '.join(missing)}"
        )
    return {name: float(value) for name, value in zip(WEEKDAY_NAMES, hours, strict=True)}


def _hours_between(start: time | None, end: time | None) -> float:
    """Hours between two times on the same day, never negative (v1)."""
    if start is None or end is None:
        return 0.0
    anchor = datetime(2000, 1, 1)  # noqa: DTZ001 -- date-free duration arithmetic
    delta = datetime.combine(anchor, end) - datetime.combine(anchor, start)
    return max(delta.total_seconds() / 3600, 0.0)


def default_working_hours() -> dict[str, float]:
    """Company working hours, used when Xero holds no working pattern (v1)."""
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


def link_staff(staff: Staff, employee_id: str) -> None:
    """Record the Xero employee id on the Staff row (the local half of v1 ``_link_staff``).

    v1 also pushed the Staff name back to Xero via ``update_employee_name``;
    that half is Phase 4 and happens in ``sync_staff`` when it lands.
    """
    logger.info("Linking staff %s (%s) to Xero employee %s", staff.id, staff.email, employee_id)
    staff.xero_user_id = employee_id
    with transaction.atomic():
        staff.save(update_fields=["xero_user_id", "updated_at"])


def syncable_staff() -> list[Staff]:
    """List current staff with a wage rate (v1's default sync population)."""
    return list(Staff.objects.filter(date_left__isnull=True, wage_rate__gt=Decimal("0")))


def sync_staff(*, dry_run: bool = False, allow_create: bool = False) -> None:
    """Link Staff rows to Xero Payroll employees, optionally creating them (v1).

    Phase 4 seam: the employee list, the name push-back and employee creation
    (with tax/leave/bank setup) are all Xero Payroll API calls. The pure
    matching engine this orchestration drives is already ported above.
    """
    raise NotImplementedError(
        f"{PHASE_4} sync_staff(dry_run={dry_run}, allow_create={allow_create}) "
        "needs the Xero Payroll employee API."
    )


def import_staff_from_xero(*, dry_run: bool = False, initial_password: str = "") -> None:
    """Create local Staff rows from Xero Payroll employees (v1).

    Phase 4 seam: every input (employees, salary/wages, working patterns) comes
    from the Xero Payroll API. ``default_working_hours`` above is the one part
    that does not and is ported.
    """
    raise NotImplementedError(
        f"{PHASE_4} import_staff_from_xero(dry_run={dry_run}) needs the "
        "Xero Payroll employee, salary and working-pattern APIs."
    )


def active_on(employee_end_date: date | None, today: date) -> bool:
    """Whether a Xero employee is still active on a date (v1 import filter)."""
    return employee_end_date is None or employee_end_date > today
