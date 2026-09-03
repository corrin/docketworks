"""Xero Payroll employee reads and writes.

The employee half of v1's ``payroll.py``, split out because it is the only
part of payroll that CREATES people in the target organisation. Its consumer
is the seed's employees phase, which re-links a restored database to a
non-production Xero org (see ``apps/xero/seeding.py``); the matching that
decides link-or-create lives in ``apps.timesheet`` and reaches these functions
through the accounting provider.

Creation is all-or-nothing by contract, not by convenience: Xero refuses to
put an employee in a pay run unless employment, salary, working pattern, tax,
bank account and leave are all present, so a partial create would return an
employee id that cannot be paid.

No manual pacing here. v1 slept 3s after every call and 10s between employees;
``RateLimitedRESTClient`` (apps/xero/client.py) is v2's one implementation of
rate limiting — it enforces the minimum gap and absorbs a minute-limit 429 by
sleeping Retry-After and retrying. A second pacing layer on top would be our
own invented constraint over a mechanism that already handles it.
"""

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal, TypedDict, cast

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.utils import timezone
from xero_python.payrollnz import (
    Address,
    BankAccount,
    Employee,
    EmployeeLeaveSetup,
    EmployeeLeaveType,
    EmployeeTax,
    EmployeeWorkingPatternWithWorkingWeeksRequest,
    Employment,
    PaymentMethod,
    PayrollNzApi,
    SalaryAndWage,
    TaxCode,
    WorkingWeek,
)

from apps.accounting.types import NewPayrollEmployee, PayrollEmployeeRef, PayrollLeaveBalance
from apps.accounts.models import Staff, StaffPayrollTerm
from apps.accounts.services.payroll_terms import WEEKDAYS
from apps.core.errors import AppErrorContext, persist_app_error
from apps.core.models import CompanyDefaults, loaded_wage_rate
from apps.timesheet.services.leave_settings import employee_leave_mappings
from apps.xero import payroll_sdk  # imported for its side effect too: applies the v1 SDK fixes
from apps.xero.auth import get_api_client, get_tenant_id
from apps.xero.helpers import as_date
from apps.xero.models import XeroPayItem
from apps.xero.operator_guards import is_production_tenant
from apps.xero.payroll_setup import get_payroll_calendars
from apps.xero.validation import XeroValidationError

logger = logging.getLogger(__name__)


# NZ standard entitlements: 4 weeks annual leave, 10 days sick leave.
ANNUAL_LEAVE_OPENING_HOURS = 160.0
SICK_LEAVE_HOURS = 80.0

# ESCT rate for the $16,801-$57,600 band, and the 3.5%/3.5% KiwiSaver split
# (the statutory minimum since 1 April 2026, up from 3%).
#
# These are SEEDING values and reach Xero only through create_payroll_employee,
# whose spec fills ird_number and bank_account_number from demo_payroll_data's
# fabricated generators — so the path cannot be used against a real
# organisation, and a production org configures its own rates. Read the spec
# builder (timesheet/services/payroll_employee_sync.py:_employee_spec) before
# concluding otherwise: the call chain alone runs through a sync that IS
# production-capable, and stopping there reads as a payroll bug that is not one.
ESCT_RATE_PERCENTAGE = 17.5
KIWISAVER_CONTRIBUTION_PERCENTAGE = 3.5

# An NZ bank account is BB-bbbb-AAAAAAA-SSS. Xero wants the bank+branch as a
# 6-digit sort code and the whole thing, undashed, as the account number.
_BANK_ACCOUNT_PARTS = 4

# User decision 2026-08-18: Xero's NZ Demo Company ships these immutable
# sample employees. They are not valid Docketworks staff and cannot be repaired
# or deleted in Xero. The only non-production payroll organisation this project
# connects is that demo org; production tenant ids are explicitly excluded below.
DEMO_EMPLOYEE_NAMES = frozenset(
    {
        "company director",
        "general manager",
        "permanent worker",
        "part time",
        "dairy milker",
        "part-time worker",
        "casual worker",
        "gst contractor",
    }
)


PayBasis = Literal["hourly", "salary"]


@dataclass(frozen=True, slots=True)
class PayrollTermSnapshot:
    """One Xero pay/work-pattern combination effective from a date."""

    effective_from: date
    pay_basis: PayBasis
    annual_salary: Decimal | None
    hourly_rate: Decimal | None
    working_weeks: list[dict[str, float]]
    salary_wage_id: str | None
    working_pattern_id: str | None


@dataclass(frozen=True, slots=True)
class PayrollEmployeeSnapshot:
    """Employee and current pay data consumed by the generic sync engine."""

    tenant_id: str
    employee_id: str
    first_name: str
    last_name: str
    email: str
    start_date: date
    end_date: date | None
    pay_basis: PayBasis
    hourly_rate: Decimal | None
    updated_date_utc: datetime
    payroll_terms: tuple[PayrollTermSnapshot, ...] = ()


@dataclass(frozen=True, slots=True)
class EmployeesForSync:
    """Collection shape expected by ``sync_xero_data``."""

    employees: list[PayrollEmployeeSnapshot]


class PartiallyCreatedEmployeeError(RuntimeError):
    """An employee exists in Xero but its pay-run prerequisites are incomplete.

    Its own class because the remedy is specific and manual: Xero's payroll
    API cannot delete an employee, so the half-built record has to be removed
    in the browser before the phase can be re-run — and a re-run that skips
    that step silently adopts it.
    """


@dataclass(frozen=True)
class _PayrollDefaults:
    """The organisation-wide ids every created employee is bound to."""

    payroll_calendar_id: str
    ordinary_earnings_rate_id: str


def _to_ref(employee: Employee) -> PayrollEmployeeRef | None:
    """Reduce an SDK employee to the matcher's view, or None if it has no id.

    An employee Xero names no id for cannot be linked to a Staff row, and
    inventing one would make the matcher claim a link that does not exist.
    """
    if not employee.employee_id:
        logger.warning(
            "Xero payroll employee %r %r has no employee_id; not matchable",
            employee.first_name,
            employee.last_name,
        )
        return None
    return PayrollEmployeeRef(
        external_id=str(employee.employee_id),
        first_name=employee.first_name or "",
        last_name=employee.last_name or "",
        email=employee.email or None,
        job_title=employee.job_title or None,
    )


def _raw_employees(payroll_api: PayrollNzApi, tenant_id: str) -> list[Employee]:
    """Fetch every active employee, following Xero's explicit page count."""
    employees: list[Employee] = []
    page = 1
    while True:
        response = payroll_api.get_employees(xero_tenant_id=tenant_id, page=page)
        if response is None:
            raise ValueError("Xero returned no response listing payroll employees")

        employees.extend(response.employees or [])
        page_count = response.pagination.page_count if response.pagination else None
        if page_count is None:
            raise ValueError(
                "Xero returned a payroll employee page with no pagination block; "
                "cannot tell whether the list is complete."
            )

        logger.info(
            "Fetched payroll employee page %d of %d (total %d)",
            page,
            page_count,
            len(employees),
        )
        if page >= page_count:
            return employees
        page += 1


def get_employees() -> list[PayrollEmployeeRef]:
    """Every active payroll employee in the connected organisation.

    Paged to exhaustion, which v1 did not do: it read page one and stopped.
    A missed page reads as "no such employee" to the matcher, and the seed's
    answer to that is to CREATE one — so under-reading here duplicates real
    people in the payroll of the target organisation.

    Termination comes from Xero's own ``pageCount``, not from a short or empty
    page. Asking this endpoint for the page after the last one answers
    **400 InvalidRequest, "Requested page does not exist"** rather than an
    empty list, so loop-until-empty turns a complete read into a failed
    command. A short-page test has the same hole at an exact multiple of the
    page size.
    """
    tenant_id = get_tenant_id()
    raw = [
        employee
        for employee in _raw_employees(PayrollNzApi(get_api_client()), tenant_id)
        if not _demo_stub(employee, tenant_id)
    ]
    refs = [ref for ref in map(_to_ref, raw) if ref is not None]

    logger.info("Retrieved %d payroll employees from Xero", len(refs))
    return refs


def _salary_and_wages(
    payroll_api: PayrollNzApi, tenant_id: str, employee_id: str
) -> list[SalaryAndWage]:
    """Fetch every salary/wage record for one employee."""
    records: list[SalaryAndWage] = []
    page = 1
    while True:
        response = payroll_api.get_employee_salary_and_wages(
            xero_tenant_id=tenant_id,
            employee_id=employee_id,
            page=page,
        )
        if response is None:
            raise ValueError(f"Xero returned no salary/wage response for employee {employee_id}")
        records.extend(response.salary_and_wages or [])
        page_count = response.pagination.page_count if response.pagination else 1
        if page_count is None:
            raise ValueError(
                f"Xero returned salary/wage pagination with no page count for {employee_id}"
            )
        if page >= page_count:
            return records
        page += 1


def _current_pay(
    records: list[SalaryAndWage],
    *,
    employee_id: str,
    effective_on: date,
    require_active: bool,
) -> tuple[PayBasis, Decimal | None]:
    """Select the latest effective valid pay record."""
    candidates: list[tuple[SalaryAndWage, date]] = []
    for row in records:
        effective_from = as_date(row.effective_from)
        if effective_from is None or effective_from > effective_on:
            continue
        if require_active and (row.status is None or row.status.lower() != "active"):
            continue
        candidates.append((row, effective_from))
    if not candidates:
        raise XeroValidationError(["current_salary_and_wage"], "employee", employee_id)
    current = max(candidates, key=lambda candidate: candidate[1])[0]
    if current.payment_type is None:
        raise XeroValidationError(["payment_type"], "employee", employee_id)
    payment_type = current.payment_type.lower()
    if payment_type == "hourly":
        if current.rate_per_unit is None or Decimal(str(current.rate_per_unit)) <= 0:
            raise XeroValidationError(["rate_per_unit"], "employee", employee_id)
        return "hourly", Decimal(str(current.rate_per_unit))
    if payment_type == "salary":
        if current.annual_salary is None or Decimal(str(current.annual_salary)) <= 0:
            raise XeroValidationError(["annual_salary"], "employee", employee_id)
        return "salary", None
    raise XeroValidationError(["payment_type"], "employee", employee_id)


def _working_patterns(
    payroll_api: PayrollNzApi, tenant_id: str, employee_id: str
) -> list[tuple[date, str | None, list[dict[str, float]]]]:
    """Fetch every effective Xero working pattern with its repeating weeks."""
    response = payroll_api.get_employee_working_patterns(
        xero_tenant_id=tenant_id, employee_id=employee_id
    )
    patterns: list[tuple[date, str | None, list[dict[str, float]]]] = []
    for summary in (response.payee_working_patterns or []) if response else []:
        pattern_id = summary.payee_working_pattern_id
        if not pattern_id:
            raise XeroValidationError(["payee_working_pattern_id"], "employee", employee_id)
        detail_response = payroll_api.get_employee_working_pattern(
            xero_tenant_id=tenant_id,
            employee_id=employee_id,
            employee_working_pattern_id=pattern_id,
        )
        detail = detail_response.payee_working_pattern if detail_response else None
        effective_from = as_date(detail.effective_from) if detail else None
        if detail is None or effective_from is None or not detail.working_weeks:
            raise XeroValidationError(["working_pattern"], "employee", employee_id)
        weeks: list[dict[str, float]] = []
        for week in detail.working_weeks:
            weeks.append({day: float(getattr(week, day) or 0) for day in WEEKDAYS})
        patterns.append((effective_from, str(pattern_id), weeks))
    return sorted(patterns, key=lambda item: item[0])


def _term_snapshots(
    pay_records: list[SalaryAndWage],
    patterns: list[tuple[date, str | None, list[dict[str, float]]]],
    employee_id: str,
) -> tuple[PayrollTermSnapshot, ...]:
    """Join independently effective pay and work-pattern records into snapshots."""
    pays: list[tuple[SalaryAndWage, date]] = []
    for row in pay_records:
        effective = as_date(row.effective_from)
        if effective is not None and str(row.status or "").lower() == "active":
            pays.append((row, effective))
    if not pays:
        return ()
    dates = sorted({effective for _row, effective in pays} | {row[0] for row in patterns})
    snapshots: list[PayrollTermSnapshot] = []
    for effective in dates:
        eligible_pay = [(row, start) for row, start in pays if start <= effective]
        eligible_pattern = [row for row in patterns if row[0] <= effective]
        if not eligible_pay:
            continue
        pay = max(eligible_pay, key=lambda item: item[1])[0]
        payment_type = str(pay.payment_type or "").lower()
        if payment_type not in {"hourly", "salary"}:
            raise XeroValidationError(["payment_type"], "employee", employee_id)
        pattern = max(eligible_pattern, key=lambda item: item[0]) if eligible_pattern else None
        if payment_type == "salary" and pattern is None:
            raise XeroValidationError(["working_pattern"], "employee", employee_id)
        annual = Decimal(str(pay.annual_salary)) if pay.annual_salary else None
        hourly = Decimal(str(pay.rate_per_unit)) if pay.rate_per_unit else None
        if payment_type == "salary" and (annual is None or annual <= 0):
            raise XeroValidationError(["annual_salary"], "employee", employee_id)
        snapshots.append(
            PayrollTermSnapshot(
                effective_from=effective,
                pay_basis=cast("PayBasis", payment_type),
                annual_salary=annual,
                hourly_rate=hourly,
                working_weeks=pattern[2] if pattern else [],
                salary_wage_id=str(pay.salary_and_wages_id) if pay.salary_and_wages_id else None,
                working_pattern_id=pattern[1] if pattern else None,
            )
        )
    return tuple(snapshots)


def _demo_stub(employee: Employee, tenant_id: str) -> bool:
    """Whether this is one of Xero's known immutable demo employees."""
    if is_production_tenant(tenant_id):
        return False
    name = f"{employee.first_name or ''} {employee.last_name or ''}".strip().casefold()
    return name in DEMO_EMPLOYEE_NAMES


def _snapshot(
    payroll_api: PayrollNzApi, tenant_id: str, employee: Employee
) -> PayrollEmployeeSnapshot:
    """Enrich one employee with the pay data Docketworks needs."""
    missing = [
        name
        for name, value in (
            ("employee_id", employee.employee_id),
            ("first_name", employee.first_name),
            ("last_name", employee.last_name),
            ("email", employee.email),
            ("start_date", employee.start_date),
            ("updated_date_utc", employee.updated_date_utc),
        )
        if value is None
    ]
    if missing:
        raise XeroValidationError(missing, "employee", str(employee.employee_id or "unknown"))
    employee_id = cast("str", employee.employee_id)
    first_name = cast("str", employee.first_name).strip()
    last_name = cast("str", employee.last_name).strip()
    email = cast("str", employee.email).strip().lower()
    start_date = as_date(employee.start_date)
    if start_date is None:
        raise XeroValidationError(["start_date"], "employee", employee_id)
    updated_date_utc = cast("datetime", employee.updated_date_utc)
    blank = [
        name
        for name, value in (
            ("first_name", first_name),
            ("last_name", last_name),
            ("email", email),
        )
        if not value
    ]
    if blank:
        raise XeroValidationError(blank, "employee", employee_id)
    try:
        validate_email(email)
    except ValidationError as exc:
        raise XeroValidationError(["email"], "employee", employee_id) from exc
    if len(first_name) > 30 or len(last_name) > 30:
        raise ValueError(
            f"Xero employee {employee_id} has a legal name longer than "
            "Docketworks' 30-character Staff fields."
        )
    end_date = as_date(employee.end_date) if employee.end_date is not None else None
    effective_on = (
        min(end_date, timezone.localdate()) if end_date is not None else timezone.localdate()
    )
    pay_records = _salary_and_wages(payroll_api, tenant_id, employee_id)
    pay_basis, hourly_rate = _current_pay(
        pay_records,
        employee_id=employee_id,
        effective_on=effective_on,
        require_active=end_date is None or end_date > timezone.localdate(),
    )
    patterns = _working_patterns(payroll_api, tenant_id, employee_id)
    return PayrollEmployeeSnapshot(
        tenant_id=tenant_id,
        employee_id=employee_id,
        first_name=first_name,
        last_name=last_name,
        email=email,
        start_date=start_date,
        end_date=end_date,
        pay_basis=pay_basis,
        hourly_rate=hourly_rate,
        updated_date_utc=updated_date_utc,
        payroll_terms=_term_snapshots(pay_records, patterns, employee_id),
    )


def get_employees_for_sync(*, xero_tenant_id: str, if_modified_since: str) -> EmployeesForSync:
    """Fetch the complete employee batch for the generic entity sync."""
    del if_modified_since  # Xero Payroll NZ exposes no employee modified-since filter.
    tenant_id = xero_tenant_id
    payroll_api = PayrollNzApi(get_api_client())
    active = [
        employee
        for employee in _raw_employees(payroll_api, tenant_id)
        if not _demo_stub(employee, tenant_id)
    ]

    active_ids = {str(employee.employee_id) for employee in active if employee.employee_id}
    linked_ids = Staff.objects.filter(
        xero_tenant_id=tenant_id, xero_user_id__isnull=False
    ).values_list("xero_user_id", flat=True)
    for linked_id in linked_ids:
        if linked_id is None:
            raise AssertionError("xero_user_id__isnull=False returned a null employee id")
        if linked_id in active_ids:
            continue
        response = payroll_api.get_employee(xero_tenant_id=tenant_id, employee_id=linked_id)
        employee = response.employee if response else None
        if employee is None:
            raise ValueError(f"Xero returned no employee for linked Staff employee id {linked_id}")
        active.append(employee)

    return EmployeesForSync(
        employees=[_snapshot(payroll_api, tenant_id, employee) for employee in active]
    )


def _email_index(staff_rows: list[Staff]) -> dict[str, set[Staff]]:
    """Index both login addresses without treating one row as a collision with itself."""
    index: dict[str, set[Staff]] = {}
    for staff in staff_rows:
        for address in (staff.office_email, staff.payroll_email):
            if not address:
                continue
            index.setdefault(address.casefold(), set()).add(staff)
    return index


def _match_staff(
    snapshot: PayrollEmployeeSnapshot,
    by_xero_id: dict[str, Staff],
    by_email: dict[str, set[Staff]],
) -> Staff | None:
    """Resolve one employee identity without choosing through an ambiguity."""
    email_matches = by_email.get(snapshot.email.casefold(), set())
    staff = by_xero_id.get(snapshot.employee_id)
    if staff is not None:
        if any(match.pk != staff.pk for match in email_matches):
            raise ValueError(
                f"Xero payroll email {snapshot.email} belongs to another Staff account"
            )
        return staff
    if len(email_matches) > 1:
        raise ValueError(f"Xero payroll email {snapshot.email} matches multiple Staff accounts")
    staff = next(iter(email_matches), None)
    if staff is not None and staff.xero_user_id:
        raise ValueError(
            f"Staff {staff.id} is linked to Xero employee {staff.xero_user_id}, "
            f"not {snapshot.employee_id}"
        )
    return staff


def _plan_employee_changes(
    snapshots: list[PayrollEmployeeSnapshot], staff_rows: list[Staff]
) -> list[tuple[PayrollEmployeeSnapshot, Staff | None]]:
    """Match the complete batch and reject duplicate claims before any write."""
    by_xero_id = {str(staff.xero_user_id): staff for staff in staff_rows if staff.xero_user_id}
    by_email = _email_index(staff_rows)
    planned: list[tuple[PayrollEmployeeSnapshot, Staff | None]] = []
    claimed_staff: set[uuid.UUID] = set()
    claimed_xero_ids: set[str] = set()
    claimed_emails: set[str] = set()
    for snapshot in snapshots:
        email = snapshot.email.casefold()
        if snapshot.employee_id in claimed_xero_ids:
            raise ValueError(f"Xero returned employee {snapshot.employee_id} more than once")
        if email in claimed_emails:
            raise ValueError(f"Multiple Xero employees use payroll email {snapshot.email}")
        claimed_xero_ids.add(snapshot.employee_id)
        claimed_emails.add(email)
        staff = _match_staff(snapshot, by_xero_id, by_email)
        if staff is not None and staff.pk in claimed_staff:
            raise ValueError(f"Multiple Xero employees match Staff {staff.id}")
        if staff is not None:
            claimed_staff.add(staff.pk)
        planned.append((snapshot, staff))
    return planned


class _XeroTermProjection(TypedDict):
    """One payroll term as the checksum sees it, from either side."""

    effective_from: date
    pay_basis: str
    annual_salary: Decimal | None
    hourly_rate: Decimal | None
    working_weeks: list[dict[str, float]]
    xero_salary_wage_id: str | None
    xero_working_pattern_id: str | None


class _XeroEmployeeProjection(TypedDict):
    """The complete Xero-owned state of one employee, from either side.

    Named rather than ``dict[str, Any]`` so the incoming and stored builders are
    provably the same shape. A field added to one and not the other would not be
    a visible failure — it would be a checksum that stops matching, and an
    employee silently rewritten on every hourly sync.
    """

    xero_tenant_id: str | None
    xero_user_id: str | None
    first_name: str
    last_name: str
    payroll_email: str | None
    employment_start_date: date | None
    date_left: date | None
    # Nullable because Staff.pay_basis is: NULL means payroll has not classified
    # this person yet, and the stored side has to be able to say so. An incoming
    # snapshot always carries one, so a NULL here differs and forces the write
    # that classifies them.
    pay_basis: str | None
    base_wage_rate: Decimal
    wage_rate: Decimal
    xero_last_modified: datetime | None
    payroll_terms: list[_XeroTermProjection]


def _money(value: Decimal) -> Decimal:
    """Round one Xero money figure to the precision its column can hold.

    Applied at the write as well as in the checksum. Xero sends rates to four
    decimals (24.0385) while every money column here is ``numeric(_, 2)``, so
    letting the database do the rounding leaves the incoming value and the
    stored value permanently unequal — a checksum that can never match, and an
    employee rewritten with a fresh payroll-term history every hour.

    ROUND_HALF_UP because Postgres rounds halves away from zero; Decimal's
    default ROUND_HALF_EVEN would disagree with the column at exactly .xx5 and
    reintroduce the same mismatch for those rates alone.
    """
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _optional_money(value: Decimal | None) -> Decimal | None:
    """Round a nullable money figure, leaving "Xero sent nothing" as NULL."""
    return None if value is None else _money(value)


def _normalise_checksum_value(value: Any) -> Any:
    """Return a deterministic JSON value for one Xero-owned payroll fact."""
    if value is None or isinstance(value, str | bool):
        return value
    if isinstance(value, datetime):
        if timezone.is_aware(value):
            value = value.astimezone(UTC)
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal | int | float):
        return format(Decimal(str(value)).normalize(), "f")
    if isinstance(value, dict):
        return {
            str(key): _normalise_checksum_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, list | tuple):
        return [_normalise_checksum_value(item) for item in value]
    raise TypeError(f"Unsupported Xero checksum value: {type(value).__name__}")


def _xero_fields_checksum(projection: _XeroEmployeeProjection) -> str:
    """Hash the complete Xero-owned employee projection deterministically."""
    serialised = json.dumps(
        _normalise_checksum_value(projection),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(serialised.encode()).hexdigest()


def _term_projection(term: PayrollTermSnapshot | StaffPayrollTerm) -> _XeroTermProjection:
    """Project either side of a payroll term into the checksum contract."""
    if isinstance(term, PayrollTermSnapshot):
        salary_wage_id = term.salary_wage_id
        working_pattern_id = term.working_pattern_id
    else:
        salary_wage_id = term.xero_salary_wage_id
        working_pattern_id = term.xero_working_pattern_id
    return {
        "effective_from": term.effective_from,
        "pay_basis": term.pay_basis,
        "annual_salary": _optional_money(term.annual_salary),
        "hourly_rate": _optional_money(term.hourly_rate),
        "working_weeks": term.working_weeks,
        "xero_salary_wage_id": salary_wage_id,
        "xero_working_pattern_id": working_pattern_id,
    }


def _snapshot_base_wage_rate(snapshot: PayrollEmployeeSnapshot) -> Decimal:
    """Return the base rate this snapshot writes, rounded as the column stores it."""
    rate = snapshot.hourly_rate
    return Decimal("0") if rate is None else _money(rate)


def _incoming_employee_projection(
    snapshot: PayrollEmployeeSnapshot, *, current_date_left: date | None, loading: Decimal
) -> _XeroEmployeeProjection:
    """Build the local state this snapshot is allowed to produce."""
    base_wage_rate = _snapshot_base_wage_rate(snapshot)
    return {
        "xero_tenant_id": snapshot.tenant_id,
        "xero_user_id": snapshot.employee_id,
        "first_name": snapshot.first_name,
        "last_name": snapshot.last_name,
        "payroll_email": snapshot.email,
        "employment_start_date": snapshot.start_date,
        # Xero null means "not yet terminated there", never "reinstate here".
        "date_left": snapshot.end_date if snapshot.end_date is not None else current_date_left,
        "pay_basis": snapshot.pay_basis,
        "base_wage_rate": base_wage_rate,
        # The derived rate is in the projection because it is the field the
        # KAN-350 incident corrupts and nothing else here implies it: leave it
        # out and a wage_rate written from a stale loading still matches the
        # checksum, so the sync skips the one write that would re-derive it.
        # Including it also makes a loading change reach every employee.
        "wage_rate": loaded_wage_rate(base_wage_rate, loading),
        "xero_last_modified": snapshot.updated_date_utc,
        "payroll_terms": [_term_projection(term) for term in snapshot.payroll_terms],
    }


def _current_employee_projection(staff: Staff) -> _XeroEmployeeProjection:
    """Build the currently persisted side of the Xero checksum contract."""
    terms = sorted(
        staff.payroll_terms.all(),
        key=lambda term: (
            term.effective_from,
            term.xero_salary_wage_id or "",
            term.xero_working_pattern_id or "",
        ),
    )
    return {
        "xero_tenant_id": staff.xero_tenant_id,
        "xero_user_id": staff.xero_user_id,
        "first_name": staff.first_name,
        "last_name": staff.last_name,
        "payroll_email": staff.payroll_email,
        "employment_start_date": staff.employment_start_date,
        "date_left": staff.date_left,
        "pay_basis": staff.pay_basis,
        "base_wage_rate": _money(staff.base_wage_rate),
        "wage_rate": staff.wage_rate,
        "xero_last_modified": staff.xero_last_modified,
        "payroll_terms": [_term_projection(term) for term in terms],
    }


def _apply_employee_change(
    snapshot: PayrollEmployeeSnapshot,
    staff: Staff | None,
    tenant_id: str,
    checksum: str,
) -> Staff:
    """Apply one already-validated and already-matched employee change."""
    base_wage_rate = _snapshot_base_wage_rate(snapshot)
    if staff is None:
        return Staff.objects.create_user(
            office_email=snapshot.email,
            password=None,
            payroll_email=snapshot.email,
            first_name=snapshot.first_name,
            last_name=snapshot.last_name,
            employment_start_date=snapshot.start_date,
            date_left=snapshot.end_date,
            pay_basis=snapshot.pay_basis,
            base_wage_rate=base_wage_rate,
            xero_user_id=snapshot.employee_id,
            xero_tenant_id=tenant_id,
            xero_last_modified=snapshot.updated_date_utc,
            xero_fields_checksum=checksum,
        )

    staff.first_name = snapshot.first_name
    staff.last_name = snapshot.last_name
    staff.payroll_email = snapshot.email
    staff.employment_start_date = snapshot.start_date
    staff.xero_user_id = snapshot.employee_id
    staff.xero_tenant_id = tenant_id
    staff.xero_last_modified = snapshot.updated_date_utc
    staff.xero_fields_checksum = checksum
    staff.pay_basis = snapshot.pay_basis
    staff.base_wage_rate = base_wage_rate
    updated_fields = [
        "first_name",
        "last_name",
        "payroll_email",
        "employment_start_date",
        "xero_user_id",
        "xero_tenant_id",
        "xero_last_modified",
        "xero_fields_checksum",
        "pay_basis",
        "base_wage_rate",
        "wage_rate",
        "updated_at",
    ]
    # Set-only, never cleared. Ending someone in Xero needs a final pay run, so
    # an employee who left months ago stays ACTIVE there with no end_date until
    # that happens — and NZ payroll exposes no termination endpoint to do it
    # with (see payroll_employee_sync). A null from Xero therefore means "Xero
    # has not been told", not "they came back", and honouring it would put a
    # departed employee back on the weekly grid and make them postable.
    # date_left is the Docketworks judgement "I do not expect this person
    # back"; reinstating someone is a deliberate local edit.
    if snapshot.end_date is not None:
        staff.date_left = snapshot.end_date
        updated_fields.append("date_left")
    staff.save(update_fields=updated_fields)
    return staff


def _replace_payroll_terms(staff: Staff, snapshot: PayrollEmployeeSnapshot) -> None:
    """Replace the complete Xero-owned term history for one employee."""
    staff.payroll_terms.all().delete()
    StaffPayrollTerm.objects.bulk_create(
        [
            StaffPayrollTerm(
                staff=staff,
                effective_from=term.effective_from,
                pay_basis=term.pay_basis,
                annual_salary=_optional_money(term.annual_salary),
                hourly_rate=_optional_money(term.hourly_rate),
                working_weeks=term.working_weeks,
                xero_salary_wage_id=term.salary_wage_id,
                xero_working_pattern_id=term.working_pattern_id,
            )
            for term in snapshot.payroll_terms
        ]
    )


def sync_employees(snapshots: list[PayrollEmployeeSnapshot]) -> None:
    """Atomically create or update Staff from one complete Xero employee batch."""
    if not snapshots:
        return
    tenant_id = snapshots[0].tenant_id
    if any(snapshot.tenant_id != tenant_id for snapshot in snapshots):
        raise ValueError("An employee sync batch cannot contain multiple Xero tenants")
    with transaction.atomic():
        staff_rows = list(Staff.objects.select_for_update().prefetch_related("payroll_terms"))
        planned = _plan_employee_changes(snapshots, staff_rows)
        # Read once for the batch, not once per employee: the projection needs
        # the loading only to derive wage_rate, and every employee in a batch
        # derives it from the same singleton inside this transaction.
        loading = CompanyDefaults.get_solo().labour_cost_loading
        for snapshot, staff in planned:
            incoming_checksum = _xero_fields_checksum(
                _incoming_employee_projection(
                    snapshot,
                    current_date_left=staff.date_left if staff is not None else None,
                    loading=loading,
                )
            )
            if staff is not None:
                current_checksum = _xero_fields_checksum(_current_employee_projection(staff))
                if staff.xero_fields_checksum == incoming_checksum == current_checksum:
                    continue
            changed = _apply_employee_change(snapshot, staff, tenant_id, incoming_checksum)
            _replace_payroll_terms(changed, snapshot)


def get_employee_leave_balances(employee_id: str) -> list[PayrollLeaveBalance]:
    """Read one employee's current leave balances through the NZ Payroll API."""
    response = PayrollNzApi(get_api_client()).get_employee_leave_balances(
        xero_tenant_id=get_tenant_id(), employee_id=employee_id
    )
    if response is None:
        raise ValueError(f"Xero returned no leave balances for employee {employee_id}")

    balances: list[PayrollLeaveBalance] = []
    for row in response.leave_balances or []:
        if not row.leave_type_id or not row.name or row.balance is None or not row.type_of_units:
            raise ValueError(
                f"Xero returned an incomplete leave balance for employee {employee_id}"
            )
        balances.append(
            PayrollLeaveBalance(
                leave_type_external_id=str(row.leave_type_id),
                name=str(row.name),
                balance=Decimal(str(row.balance)),
                unit=str(row.type_of_units),
            )
        )
    return balances


def _payroll_defaults() -> _PayrollDefaults:
    """Resolve the calendar and earnings rate every created employee needs.

    Resolved here rather than passed in: they are Xero identifiers, and the
    domain layer that builds the employee spec has no business holding them.
    """
    calendar_name = CompanyDefaults.get_solo().xero_payroll_calendar_name
    if not calendar_name:
        raise ValueError(
            "CompanyDefaults.xero_payroll_calendar_name is not set; "
            "run manage.py xero --setup before creating payroll employees."
        )

    target = calendar_name.strip().lower()
    calendar_id = next(
        (
            cal.id
            for cal in get_payroll_calendars(tenant_id=payroll_sdk.connected_tenant())
            if cal.name.strip().lower() == target
        ),
        None,
    )
    if not calendar_id:
        raise ValueError(
            f"Payroll calendar {calendar_name!r} does not exist in the connected "
            "organisation; run manage.py xero --setup --seed-xero to create it."
        )

    ordinary_time = XeroPayItem.get_ordinary_time()
    if ordinary_time is None or not ordinary_time.xero_id:
        raise ValueError(
            "The 'Ordinary Time' earnings rate is not linked to this organisation; "
            "run manage.py xero --configure-payroll first."
        )

    return _PayrollDefaults(
        payroll_calendar_id=calendar_id,
        ordinary_earnings_rate_id=ordinary_time.xero_id,
    )


def _create_employment(
    payroll_api: PayrollNzApi,
    tenant_id: str,
    employee_id: str,
    defaults: _PayrollDefaults,
    start: date,
) -> None:
    """Put the employee on the payroll calendar.

    Without this Xero holds a person who is on no calendar, and refuses to
    create a pay run for that calendar at all. ``engagement_type`` is omitted:
    the demo organisation rejects it.
    """
    employment = Employment(
        payroll_calendar_id=defaults.payroll_calendar_id,
        start_date=start,
    )
    payroll_api.create_employment(
        xero_tenant_id=tenant_id, employee_id=employee_id, employment=employment
    )
    logger.info("Created employment for payroll employee %s", employee_id)


def _create_salary_and_wage(
    payroll_api: PayrollNzApi,
    tenant_id: str,
    employee_id: str,
    spec: NewPayrollEmployee,
    defaults: _PayrollDefaults,
) -> None:
    """Record the hourly rate. Must precede the working pattern.

    ``annual_salary`` and ``status`` are meaningless for an hourly employee
    but the SDK validates them client-side, so they are supplied rather than
    omitted.
    """
    total_hours = sum(spec.hours_per_week.values())
    working_days = sum(1 for hours in spec.hours_per_week.values() if hours > 0)
    if not working_days:
        raise ValueError(
            f"Staff {spec.staff_id} ({spec.email}) has no working days; "
            "a payroll employee needs at least one."
        )

    salary_and_wage = SalaryAndWage(
        earnings_rate_id=defaults.ordinary_earnings_rate_id,
        number_of_units_per_week=total_hours,
        number_of_units_per_day=total_hours / working_days,
        days_per_week=working_days,
        rate_per_unit=float(spec.hourly_rate),
        annual_salary=0,
        status="Active",
        effective_from=spec.start_date,
        payment_type="Hourly",
    )
    payroll_api.create_employee_salary_and_wage(
        xero_tenant_id=tenant_id, employee_id=employee_id, salary_and_wage=salary_and_wage
    )
    logger.info(
        "Created salary for payroll employee %s (%s/hr, %.1f hrs/week)",
        employee_id,
        spec.hourly_rate,
        total_hours,
    )


def _create_working_pattern(
    payroll_api: PayrollNzApi, tenant_id: str, employee_id: str, spec: NewPayrollEmployee
) -> None:
    """Record the weekly hours. Requires the salary record to exist first."""
    payroll_api.create_employee_working_pattern(
        xero_tenant_id=tenant_id,
        employee_id=employee_id,
        employee_working_pattern_with_working_weeks_request=(
            EmployeeWorkingPatternWithWorkingWeeksRequest(
                effective_from=spec.start_date,
                working_weeks=[WorkingWeek(**spec.hours_per_week)],
            )
        ),
    )
    logger.info("Created working pattern for payroll employee %s", employee_id)


def _create_employee_tax(
    payroll_api: PayrollNzApi, tenant_id: str, employee_id: str, ird_number: str
) -> None:
    """Set the IRD number, tax code and KiwiSaver — required for a pay run."""
    payroll_api.update_employee_tax(
        xero_tenant_id=tenant_id,
        employee_id=employee_id,
        employee_tax=EmployeeTax(
            ird_number=ird_number.replace("-", "").zfill(9),
            tax_code=TaxCode.M,
            esct_rate_percentage=ESCT_RATE_PERCENTAGE,
            is_eligible_for_kiwi_saver=True,
            kiwi_saver_contributions="MakeContributions",
            kiwi_saver_employee_contribution_rate_percentage=KIWISAVER_CONTRIBUTION_PERCENTAGE,
            kiwi_saver_employer_contribution_rate_percentage=KIWISAVER_CONTRIBUTION_PERCENTAGE,
            kiwi_saver_employer_salary_sacrifice_contribution_rate_percentage=0.0,
        ),
    )
    logger.info("Set tax details for payroll employee %s", employee_id)


def _create_employee_payment_method(
    payroll_api: PayrollNzApi, tenant_id: str, employee_id: str, bank_account_number: str
) -> None:
    """Set the wages bank account — required for a pay run."""
    parts = bank_account_number.split("-")
    if len(parts) != _BANK_ACCOUNT_PARTS:
        raise ValueError(
            f"Invalid NZ bank account {bank_account_number!r}; expected BB-bbbb-AAAAAAA-SSS"
        )

    payroll_api.create_employee_payment_method(
        xero_tenant_id=tenant_id,
        employee_id=employee_id,
        payment_method=PaymentMethod(
            payment_method="Electronically",
            bank_accounts=[
                BankAccount(
                    account_name="Wages",
                    account_number="".join(parts),
                    sort_code=f"{parts[0]}{parts[1]}",
                    calculation_type="Balance",
                )
            ],
        ),
    )
    logger.info("Set payment method for payroll employee %s", employee_id)


def _create_employee_leave_setup(
    payroll_api: PayrollNzApi, tenant_id: str, employee_id: str
) -> None:
    """Set leave entitlements — required for a pay run."""
    payroll_api.create_employee_leave_setup(
        xero_tenant_id=tenant_id,
        employee_id=employee_id,
        employee_leave_setup=EmployeeLeaveSetup(
            include_holiday_pay=False,
            holiday_pay_opening_balance=0.0,
            annual_leave_opening_balance=ANNUAL_LEAVE_OPENING_HOURS,
            sick_leave_to_accrue_annually=SICK_LEAVE_HOURS,
            sick_leave_maximum_to_accrue=SICK_LEAVE_HOURS,
            sick_leave_opening_balance=SICK_LEAVE_HOURS,
        ),
    )
    logger.info("Set leave entitlements for payroll employee %s", employee_id)


def employee_leave_type_ids(employee_id: str) -> set[str]:
    """Return the leave type ids currently assigned to one Xero employee."""
    response = PayrollNzApi(get_api_client()).get_employee_leave_types(
        xero_tenant_id=get_tenant_id(), employee_id=employee_id
    )
    if response is None:
        raise ValueError(f"Xero returned no leave types for employee {employee_id}")
    return {
        str(leave_type.leave_type_id)
        for leave_type in (response.leave_types or [])
        if leave_type.leave_type_id
    }


def missing_employee_leave_types(employee_id: str) -> list[str]:
    """Name the Docketworks leave types not assigned to one employee."""
    required = employee_leave_mappings()
    assigned = employee_leave_type_ids(employee_id)
    return [row.display_name for row in required if row.external_id not in assigned]


def ensure_employee_leave_types(employee_id: str) -> set[str]:
    """Make an employee eligible for every leave type Docketworks posts.

    Xero's standard leave setup owns Annual and Sick accrual rules. Unpaid and
    Bereavement are explicitly assigned with no accrual and zero opening
    balance; inventing accrual rules for either would change payroll policy.
    The final read-back is the readiness check used by both creation and seed
    repair.
    """
    tenant_id = str(get_tenant_id())
    required = employee_leave_mappings()
    assigned = employee_leave_type_ids(employee_id)

    missing_standard = [
        row.display_name
        for row in required
        if row.standard_entitlement and row.external_id not in assigned
    ]
    if missing_standard:
        raise ValueError(
            f"Xero employee {employee_id} is missing standard leave setup for "
            + ", ".join(sorted(missing_standard))
            + "; repair the employee's standard leave setup in Xero."
        )

    api = PayrollNzApi(get_api_client())
    for mapping in required:
        if mapping.standard_entitlement or mapping.external_id in assigned:
            continue
        response = api.create_employee_leave_type(
            xero_tenant_id=tenant_id,
            employee_id=employee_id,
            employee_leave_type=EmployeeLeaveType(
                leave_type_id=mapping.external_id,
                schedule_of_accrual="NoAccruals",
                opening_balance=0.0,
            ),
        )
        returned = response.leave_type if response else None
        if returned is None or str(returned.leave_type_id) != mapping.external_id:
            raise ValueError(
                f"Xero did not confirm {mapping.display_name} "
                f"({mapping.external_id}) for employee {employee_id}"
            )
        assigned.add(mapping.external_id)

    assigned = employee_leave_type_ids(employee_id)
    missing = [row.display_name for row in required if row.external_id not in assigned]
    if missing:
        raise ValueError(f"Xero employee {employee_id} is not eligible for: " + ", ".join(missing))
    return assigned


def create_payroll_employee(spec: NewPayrollEmployee) -> PayrollEmployeeRef:
    """Create a payroll employee and everything a pay run needs from it.

    The call order below is load-bearing and was established against live
    Xero: employment before salary (an employee on no calendar cannot hold a
    salary record), and salary before the working pattern (Xero rejects a
    pattern for an employee with no salary).
    """
    tenant_id = get_tenant_id()
    payroll_api = PayrollNzApi(get_api_client())
    # Resolved before the first write: a missing calendar or earnings rate
    # would otherwise be discovered after the employee already exists in Xero,
    # leaving a person nothing can finish setting up.
    defaults = _payroll_defaults()

    try:
        # Only the seven fields proven nullable in Xero responses are relaxed
        # by payroll_sdk. The employee's other required fields are still the
        # last validation between a malformed Staff row and Xero.
        employee = Employee(
            first_name=spec.first_name,
            last_name=spec.last_name,
            email=spec.email,
            date_of_birth=spec.date_of_birth,
            start_date=spec.start_date,
            end_date=spec.end_date,
            job_title=spec.job_title,
            address=Address(
                address_line1=spec.address.address_line1,
                address_line2=spec.address.address_line2,
                suburb=spec.address.suburb,
                city=spec.address.city,
                post_code=spec.address.post_code,
                country_name=spec.address.country_name,
            ),
        )
        response = payroll_api.create_employee(xero_tenant_id=tenant_id, employee=employee)
        created = response.employee if response else None
        if created is None:
            raise ValueError(f"Xero accepted the create for {spec.email} but returned no employee")
        ref = _to_ref(created)
        if ref is None:
            raise ValueError(f"Xero created an employee for {spec.email} with no employee_id")

        employee_id = ref.external_id
        # From here the person EXISTS in Xero and is incomplete. Nothing can
        # undo that — the payroll API has no delete, only termination — and a
        # re-run would match this half-built employee by the Staff UUID in its
        # job title, link it, and report the mirror converged over someone who
        # cannot be paid. So the failure carries the remedy rather than the
        # operator having to work it out from a stack trace.
        try:
            _create_employment(payroll_api, tenant_id, employee_id, defaults, spec.start_date)
            _create_salary_and_wage(payroll_api, tenant_id, employee_id, spec, defaults)
            _create_working_pattern(payroll_api, tenant_id, employee_id, spec)
            _create_employee_tax(payroll_api, tenant_id, employee_id, spec.ird_number)
            _create_employee_payment_method(
                payroll_api, tenant_id, employee_id, spec.bank_account_number
            )
            _create_employee_leave_setup(payroll_api, tenant_id, employee_id)
            ensure_employee_leave_types(employee_id)
        except Exception as exc:
            raise PartiallyCreatedEmployeeError(
                f"Xero employee {employee_id} was created for {spec.email} but its setup "
                f"did not finish: {exc}. That employee cannot be paid, and re-running as-is "
                "would adopt it and report the seed converged. In Xero, delete or terminate "
                f"the employee named '{spec.first_name} {spec.last_name}' with job title "
                f"'{spec.job_title}', then re-run the employees phase."
            ) from exc
    except Exception as exc:
        persist_app_error(
            exc,
            AppErrorContext(
                additional_context={
                    "operation": "create_payroll_employee",
                    "staff_id": str(spec.staff_id),
                    "email": spec.email,
                }
            ),
        )
        raise

    logger.info("Created payroll employee %s for staff %s", employee_id, spec.staff_id)
    return ref


def update_employee_name(external_id: str, first_name: str, last_name: str) -> None:
    """Rename an existing payroll employee to match the local Staff row.

    Read-modify-write rather than a name-only patch: Xero's update replaces
    the whole employee, so anything not sent back is cleared.
    """
    tenant_id = get_tenant_id()
    payroll_api = PayrollNzApi(get_api_client())

    response = payroll_api.get_employee(xero_tenant_id=tenant_id, employee_id=external_id)
    existing = response.employee if response else None
    if existing is None:
        raise ValueError(f"Xero payroll employee {external_id} not found")

    # Xero's demo organisation serialises an unset gender as the literal
    # string "None", which its own update endpoint then rejects.
    if existing.gender == "None":
        existing.gender = None

    existing.first_name = first_name
    existing.last_name = last_name
    payroll_api.update_employee(
        xero_tenant_id=tenant_id, employee_id=external_id, employee=existing
    )
    logger.info("Renamed payroll employee %s to %s %s", external_id, first_name, last_name)
