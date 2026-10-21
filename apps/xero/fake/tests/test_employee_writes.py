"""The seed's employees phase runs unchanged against the fake (ADR 0060).

Business risk covered: ``sync_staff(allow_create=True)`` is how a fresh
installation or a restored copy gets its staff into payroll. It renames an
employee it matches and creates, step by step, every record a pay run needs
for one it does not. A fake missing any of those routes fails the phase
part-way; one that answered without keeping what it was sent would let the
phase pass and then hand the detail refresh, the leave service or a pay run
an employee Xero would have held differently. So the phase is driven through
the real registry, provider and SDK, and the result is read back through the
fake's own reads.
"""

import uuid
from collections.abc import Iterator
from datetime import date
from decimal import Decimal

import pytest
from xero_python.payrollnz import Address, Employee, Employment, PayrollNzApi

from apps.accounts.models import Staff
from apps.company.tests.factories import make_company
from apps.core.models import CompanyDefaults
from apps.timesheet.services.payroll_employee_sync import sync_staff
from apps.timesheet.tests.conftest import make_leave_job, make_staff
from apps.xero.auth import get_api_client
from apps.xero.fake.models import FakeEmployee, FakeEmployeeTax, FakePaymentMethod
from apps.xero.fake.seed import seed_payroll
from apps.xero.fake.testing import CALENDAR_ID, connected_to_the_fake
from apps.xero.models import XeroPayItem

pytestmark = pytest.mark.django_db

TENANT = "22222222-2222-2222-2222-222222222222"
LEAVE_API_TYPES = ("Annual Leave", "Sick Leave", "Bereavement Leave", "Unpaid Leave")


@pytest.fixture
def fake_payroll() -> Iterator[PayrollNzApi]:
    """The process on the fake, its payroll configured as onboarding leaves it."""
    with connected_to_the_fake(TENANT):
        CompanyDefaults.objects.filter(pk=CompanyDefaults.singleton_instance_id).update(
            xero_payroll_calendar_name="Weekly",
            address_line1="1 Shop Street",
            city="Wellington",
            post_code="6011",
            country="NEW ZEALAND",
        )
        CompanyDefaults.clear_cache()
        # The organisation's pay items carry Xero ids; Holiday Pay is the
        # leave type Xero's own leave setup assigns beside annual and sick.
        XeroPayItem.objects.get_or_create(name="Holiday Pay", uses_leave_api=True)
        for item in XeroPayItem.objects.filter(
            name__in=(*LEAVE_API_TYPES, "Holiday Pay", "Ordinary Time")
        ):
            item.xero_id = str(uuid.uuid4())
            item.xero_tenant_id = TENANT
            item.save(update_fields=["xero_id", "xero_tenant_id"])
        superuser = make_staff("payroll-super@example.test", is_superuser=True, xero_user_id="")
        company = make_company("Payroll Leave Jobs")
        for name in LEAVE_API_TYPES:
            make_leave_job(company, superuser, name)
        seed_payroll(TENANT, CALENDAR_ID)
        yield PayrollNzApi(get_api_client())


def _unlinked(email: str, first_name: str, last_name: str) -> Staff:
    return make_staff(
        email,
        xero_user_id="",
        first_name=first_name,
        last_name=last_name,
        base_wage_rate=Decimal("31.50"),
        hours_mon=8,
        hours_tue=8,
        hours_wed=8,
        hours_thu=8,
        hours_fri=6,
        hours_sat=0,
        hours_sun=0,
    )


def test_an_unmatched_staff_member_is_created_with_everything_a_pay_run_needs(
    fake_payroll: PayrollNzApi,
) -> None:
    staff = _unlinked("new-hire@example.test", "Nora", "Newhire")

    result = sync_staff([staff], tenant_id=TENANT, allow_create=True)

    assert len(result.created) == 1
    staff.refresh_from_db()
    assert staff.xero_user_id is not None
    employee_id = str(staff.xero_user_id)

    listed = fake_payroll.get_employees(TENANT, page=1).employees or []
    assert employee_id in {str(row.employee_id) for row in listed}
    employee = fake_payroll.get_employee(TENANT, employee_id).employee
    assert employee is not None
    assert (employee.first_name, employee.last_name) == ("Nora", "Newhire")
    assert employee.email == "new-hire@example.test"
    # The employment's calendar and start date, read off the store: the SDK's
    # Employee stub declares neither as the wire carries it.
    held = FakeEmployee.objects.get(id=staff.xero_user_id)
    assert str(held.payroll_calendar_id) == CALENDAR_ID
    assert held.start_date == staff.employment_start_date

    pay = fake_payroll.get_employee_salary_and_wages(TENANT, employee_id).salary_and_wages
    assert pay is not None and len(pay) == 1
    assert Decimal(str(pay[0].rate_per_unit)) == Decimal("31.50")
    assert pay[0].number_of_units_per_week == 38.0

    patterns = fake_payroll.get_employee_working_patterns(TENANT, employee_id)
    assert patterns.payee_working_patterns is not None
    assert len(patterns.payee_working_patterns) == 1
    weeks = fake_payroll.get_employee_working_pattern(
        TENANT, employee_id, str(patterns.payee_working_patterns[0].payee_working_pattern_id)
    ).payee_working_pattern
    assert weeks is not None and weeks.working_weeks is not None
    assert weeks.working_weeks[0].friday == 6.0

    leave_types = fake_payroll.get_employee_leave_types(TENANT, employee_id).leave_types
    assigned = {
        XeroPayItem.objects.get(xero_id=str(row.leave_type_id), uses_leave_api=True).name
        for row in leave_types or []
    }
    assert assigned == {"Holiday Pay", *LEAVE_API_TYPES}
    balances = fake_payroll.get_employee_leave_balances(TENANT, employee_id).leave_balances
    by_name = {row.name: row.balance for row in balances or []}
    assert by_name["Annual Leave"] == 160.0
    assert by_name["Sick Leave"] == 80.0
    assert by_name["Unpaid Leave"] == 0.0

    # No read route exists for these two; the pay run is what will read them.
    assert FakeEmployeeTax.objects.get(employee=held).attributes["taxCode"] == "M"
    accounts = FakePaymentMethod.objects.get(employee=held).attributes["bankAccounts"]
    assert len(accounts) == 1


def test_a_matched_staff_member_is_linked_and_the_employee_renamed(
    fake_payroll: PayrollNzApi,
) -> None:
    existing = fake_payroll.create_employee(
        TENANT,
        Employee(
            first_name="Previous",
            last_name="Owner",
            email="matched@example.test",
            date_of_birth=date(1990, 1, 1),
            address=Address(
                address_line1="1 Shop Street",
                city="Wellington",
                post_code="6011",
                country_name="NEW ZEALAND",
            ),
        ),
    ).employee
    assert existing is not None and existing.employee_id is not None
    # Every employee an organisation already holds is on a calendar.
    fake_payroll.create_employment(
        TENANT,
        str(existing.employee_id),
        Employment(payroll_calendar_id=CALENDAR_ID, start_date=date(2024, 2, 1)),
    )
    staff = _unlinked("matched@example.test", "Mara", "Matched")

    result = sync_staff([staff], tenant_id=TENANT, allow_create=True)

    assert len(result.linked) == 1 and not result.created
    staff.refresh_from_db()
    assert str(staff.xero_user_id) == str(existing.employee_id)
    renamed = fake_payroll.get_employee(TENANT, str(existing.employee_id)).employee
    assert renamed is not None
    assert (renamed.first_name, renamed.last_name) == ("Mara", "Matched")
    assert renamed.email == "matched@example.test"
    listed = fake_payroll.get_employees(TENANT, page=1).employees or []
    assert [row.employee_id for row in listed].count(existing.employee_id) == 1
