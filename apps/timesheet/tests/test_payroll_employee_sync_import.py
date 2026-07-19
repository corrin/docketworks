"""Tests for importing Staff from Xero Payroll employees."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, Optional
from unittest.mock import patch

from apps.testing import BaseTestCase
from apps.timesheet.services.payroll_employee_sync import PayrollEmployeeSyncService
from apps.workflow.api.xero.payroll import coerce_xero_date
from apps.workflow.models import CompanyDefaults


@dataclass
class FakeXeroEmployee:
    """Stand-in for a Xero Payroll NZ employee.

    ``end_date`` is a ``datetime`` because that is what the Xero SDK deserializes
    it to — the distinction this test exists to protect.
    """

    employee_id: str
    first_name: str
    last_name: str
    email: str
    end_date: Optional[datetime]


@dataclass
class FakeSalaryAndWage:
    status: str = "Active"
    rate_per_unit: Decimal = Decimal("32.50")


class ImportStaffFromXeroActiveFilterTests(BaseTestCase):
    """The active-employee filter must survive Xero's datetime end_dates."""

    def setUp(self) -> None:
        super().setUp()
        company = CompanyDefaults.get_solo()
        company.xero_payroll_calendar_name = "Weekly"
        company.save(update_fields=["xero_payroll_calendar_name"])

        now = datetime.now()
        self.current_employee = FakeXeroEmployee(
            employee_id="11111111-1111-1111-1111-111111111111",
            first_name="Current",
            last_name="Worker",
            email="current@example.com",
            end_date=None,
        )
        self.leaving_employee = FakeXeroEmployee(
            employee_id="22222222-2222-2222-2222-222222222222",
            first_name="Leaving",
            last_name="Worker",
            email="leaving@example.com",
            end_date=now + timedelta(days=30),
        )
        self.departed_employee = FakeXeroEmployee(
            employee_id="33333333-3333-3333-3333-333333333333",
            first_name="Departed",
            last_name="Worker",
            email="departed@example.com",
            end_date=now - timedelta(days=30),
        )

    def _import(self) -> Dict[str, Any]:
        employees = [
            self.current_employee,
            self.leaving_employee,
            self.departed_employee,
        ]
        module = "apps.timesheet.services.payroll_employee_sync"
        with (
            patch(f"{module}.get_employees", return_value=employees),
            patch(
                f"{module}.get_employee_salary_and_wages",
                return_value=[FakeSalaryAndWage()],
            ),
            patch(f"{module}.get_employee_working_patterns", return_value=[]),
        ):
            return PayrollEmployeeSyncService.import_staff_from_xero(
                dry_run=True,
                initial_password="irrelevant-for-dry-run",
            )

    def test_datetime_end_date_does_not_break_the_filter(self) -> None:
        """A terminated employee carries a datetime end_date; comparing it to
        date.today() raised TypeError and made --import-staff unusable on any
        tenant with past employees."""
        summary = self._import()

        self.assertEqual(summary["total_xero_employees"], 3)
        self.assertEqual(summary["active_employees"], 2)

    def test_departed_employee_is_not_imported(self) -> None:
        summary = self._import()

        imported = {item["employee"] for item in summary["created"]}
        self.assertIn("Current Worker (current@example.com)", imported)
        self.assertIn("Leaving Worker (leaving@example.com)", imported)
        self.assertNotIn("Departed Worker (departed@example.com)", imported)
        self.assertEqual(summary["errors"], [])


class CoerceXeroDateTests(BaseTestCase):
    """The shared normalizer is the contract the filter above depends on."""

    def test_datetime_becomes_date(self) -> None:
        self.assertEqual(
            coerce_xero_date(datetime(2026, 3, 4, 15, 30)), date(2026, 3, 4)
        )
