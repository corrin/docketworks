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

import logging
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

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
from apps.core.errors import AppErrorContext, persist_app_error
from apps.core.models import CompanyDefaults
from apps.timesheet.services.leave_settings import employee_leave_mappings
from apps.xero import payroll_sdk as _payroll_sdk  # noqa: F401 -- applies v1 SDK fixes
from apps.xero.auth import get_api_client, get_tenant_id
from apps.xero.models import XeroPayItem
from apps.xero.payroll_setup import get_payroll_calendars

logger = logging.getLogger(__name__)


# NZ standard entitlements: 4 weeks annual leave, 10 days sick leave.
ANNUAL_LEAVE_OPENING_HOURS = 160.0
SICK_LEAVE_HOURS = 80.0

# ESCT rate for the $16,801-$57,600 band, and the standard 3%/3% KiwiSaver
# split. Demo-organisation values; a production org configures its own.
ESCT_RATE_PERCENTAGE = 17.5
KIWISAVER_CONTRIBUTION_PERCENTAGE = 3.0

# An NZ bank account is BB-bbbb-AAAAAAA-SSS. Xero wants the bank+branch as a
# 6-digit sort code and the whole thing, undashed, as the account number.
_BANK_ACCOUNT_PARTS = 4


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


def get_employees() -> list[PayrollEmployeeRef]:
    """Every payroll employee in the connected organisation.

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
    payroll_api = PayrollNzApi(get_api_client())

    refs: list[PayrollEmployeeRef] = []
    page = 1
    while True:
        response = payroll_api.get_employees(xero_tenant_id=tenant_id, page=page)
        if response is None:
            raise ValueError("Xero returned no response listing payroll employees")

        refs.extend(ref for ref in map(_to_ref, response.employees or []) if ref is not None)

        # Refused rather than defaulted (ADR 0015): without a page count there
        # is no way to tell "that was everything" from "that was page one of
        # four", and guessing the first duplicates every employee we did not
        # read.
        page_count = response.pagination.page_count if response.pagination else None
        if page_count is None:
            raise ValueError(
                "Xero returned a payroll employee page with no pagination block; "
                "cannot tell whether the list is complete."
            )

        logger.info(
            "Fetched payroll employee page %d of %d (total %d)", page, page_count, len(refs)
        )
        if page >= page_count:
            break
        page += 1

    logger.info("Retrieved %d payroll employees from Xero", len(refs))
    return refs


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
        (cal.id for cal in get_payroll_calendars() if cal.name.strip().lower() == target),
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
