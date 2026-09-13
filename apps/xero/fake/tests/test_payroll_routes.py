"""The fake answers the Payroll NZ reads the sync makes, through the real SDK (ADR 0060).

Business risk covered: the detail refresh pages employees by Xero's own
page count and reads each one's pay and pattern back; a page that lied or a
term that came back changed would make an iteration run rewrite Staff.
That the sync sees no change is proven end to end in
apps/xero/tests/test_fake_managers.py; here, the routes answer what was seeded.
"""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from xero_python.exceptions import ApiException
from xero_python.payrollnz import PayrollNzApi

from apps.accounts.models import Staff, StaffPayrollTerm
from apps.xero.fake.seed import seed_payroll
from apps.xero.fake.store import FakeXeroStore
from apps.xero.fake.tests.conftest import TENANT

pytestmark = pytest.mark.django_db
CALENDAR = "d015dc21-981e-4d26-a9cc-f8e8432fc76d"


def _linked_staff(email: str, *, hourly_rate: str) -> Staff:
    staff = Staff.objects.create_user(
        email,
        "x",
        first_name="Ada",
        last_name="Lovelace",
        payroll_email=email,
        employment_start_date=date(2025, 4, 1),
        pay_basis="hourly",
        base_wage_rate=Decimal(hourly_rate),
        xero_user_id=None,
        xero_tenant_id=TENANT,
        xero_last_modified=datetime(2026, 9, 12, 3, 49, 26, tzinfo=UTC),
    )
    staff.xero_user_id = "3cedd91a-f903-4bdb-ae51-8078be2f5795"
    staff.save(update_fields=["xero_user_id"])
    StaffPayrollTerm.objects.create(
        staff=staff,
        effective_from=date(2025, 4, 1),
        pay_basis="hourly",
        hourly_rate=Decimal(hourly_rate),
        working_weeks=[
            {
                "monday": 8.0,
                "tuesday": 8.0,
                "wednesday": 8.0,
                "thursday": 8.0,
                "friday": 8.0,
                "saturday": 0.0,
                "sunday": 0.0,
            }
        ],
        xero_salary_wage_id="ff3162ad-b084-4203-b924-2aa18b3b5055",
        xero_working_pattern_id="664daf9d-33ec-43db-bf65-60338d4593ce",
    )
    return staff


class TestEmployees:
    def test_paging_stops_where_xero_says_and_a_page_past_it_is_a_400(
        self, store: FakeXeroStore, payroll: PayrollNzApi
    ) -> None:
        _linked_staff("ada@example.test", hourly_rate="36.05")
        seed_payroll(store, CALENDAR)
        page = payroll.get_employees(TENANT, page=1)
        assert page.pagination is not None
        assert page.pagination.page_count == 1
        assert page.employees is not None and len(page.employees) == 1
        assert page.employees[0].start_date is not None
        with pytest.raises(ApiException) as refused:
            payroll.get_employees(TENANT, page=2)
        assert refused.value.status == 400

    def test_an_employee_carries_the_address_xero_was_given(
        self, store: FakeXeroStore, payroll: PayrollNzApi
    ) -> None:
        # The E2E user has an office address and no payroll one; the real seed
        # created its employee with the office address, so that is what Xero
        # holds and what the inbound sync requires.
        staff = _linked_staff("office@example.test", hourly_rate="36.05")
        staff.payroll_email = None
        staff.save(update_fields=["payroll_email"])
        seed_payroll(store, CALENDAR)
        employee = payroll.get_employee(TENANT, str(staff.xero_user_id)).employee
        assert employee is not None and employee.email == "office@example.test"

    def test_the_detail_routes_answer_the_seeded_terms(
        self, store: FakeXeroStore, payroll: PayrollNzApi
    ) -> None:
        staff = _linked_staff("ada@example.test", hourly_rate="36.05")
        seed_payroll(store, CALENDAR)
        employee_id = str(staff.xero_user_id)
        pay = payroll.get_employee_salary_and_wages(TENANT, employee_id).salary_and_wages
        assert pay is not None and Decimal(str(pay[0].rate_per_unit)) == Decimal("36.05")
        patterns = payroll.get_employee_working_patterns(TENANT, employee_id).payee_working_patterns
        assert patterns is not None and len(patterns) == 1
        detail = payroll.get_employee_working_pattern(
            TENANT, employee_id, str(patterns[0].payee_working_pattern_id)
        ).payee_working_pattern
        assert detail is not None and detail.working_weeks is not None
        assert detail.working_weeks[0].monday == 8.0
        assert detail.working_weeks[0].saturday == 0.0
