"""Tests for importing Staff from Xero Payroll employees."""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

from apps.accounts.models import Staff
from apps.testing import BaseTestCase
from apps.timesheet.services.payroll_employee_sync import PayrollEmployeeSyncService
from apps.workflow.api.xero.payroll import (
    coerce_xero_date,
    get_employee_working_patterns,
)
from apps.workflow.models import CompanyDefaults

PAYROLL = "apps.workflow.api.xero.payroll"
SYNC = "apps.timesheet.services.payroll_employee_sync"


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


@dataclass
class FakeWorkingWeek:
    monday: float = 8.0
    tuesday: float = 8.0
    wednesday: float = 8.0
    thursday: float = 8.0
    friday: float = 6.0
    saturday: float = 0.0
    sunday: float = 0.0


@dataclass
class FakePatternSummary:
    """Mirrors EmployeeWorkingPattern: identifiers and dates only, no hours."""

    payee_working_pattern_id: str
    effective_from: Optional[datetime]


@dataclass
class FakePatternsResponse:
    """Mirrors EmployeeWorkingPatternsObject."""

    payee_working_patterns: Optional[List[FakePatternSummary]]


@dataclass
class FakePatternWithWeeks:
    """Mirrors EmployeeWorkingPatternWithWorkingWeeks."""

    working_weeks: List[FakeWorkingWeek] = field(default_factory=list)


@dataclass
class FakePatternDetail:
    """Mirrors EmployeeWorkingPatternWithWorkingWeeksObject."""

    payee_working_pattern: FakePatternWithWeeks


def _patched_payroll_api(patterns_response: Any, detail_response: Any) -> MagicMock:
    api = MagicMock()
    api.get_employee_working_patterns.return_value = patterns_response
    api.get_employee_working_pattern.return_value = detail_response
    return api


class GetEmployeeWorkingPatternsTests(BaseTestCase):
    """Xero returns pattern IDs from the list call and hours from a second call.

    Reading hours off the list response returned nothing and raised — the import
    could never seed a new hire's weekly hours.
    """

    EMPLOYEE_ID = "11111111-1111-1111-1111-111111111111"

    def _call(self, patterns_response: Any, detail_response: Any = None) -> Any:
        api = _patched_payroll_api(patterns_response, detail_response)
        with (
            patch(f"{PAYROLL}.get_tenant_id", return_value="tenant-1"),
            patch(f"{PAYROLL}.PayrollNzApi", return_value=api),
            patch(f"{PAYROLL}.time.sleep"),
        ):
            return get_employee_working_patterns(self.EMPLOYEE_ID), api

    def test_returns_hours_from_the_detail_call(self) -> None:
        summaries = [
            FakePatternSummary(
                payee_working_pattern_id="pattern-1",
                effective_from=datetime.now() - timedelta(days=10),
            )
        ]
        detail = FakePatternDetail(
            payee_working_pattern=FakePatternWithWeeks(
                working_weeks=[FakeWorkingWeek()]
            )
        )

        result, api = self._call(FakePatternsResponse(summaries), detail)

        self.assertEqual(
            result,
            [
                {
                    "monday": 8.0,
                    "tuesday": 8.0,
                    "wednesday": 8.0,
                    "thursday": 8.0,
                    "friday": 6.0,
                    "saturday": 0.0,
                    "sunday": 0.0,
                }
            ],
        )
        api.get_employee_working_pattern.assert_called_once()
        self.assertEqual(
            api.get_employee_working_pattern.call_args.kwargs[
                "employee_working_pattern_id"
            ],
            "pattern-1",
        )

    def test_picks_the_latest_pattern_already_in_effect(self) -> None:
        """effective_from arrives as a datetime; ordering must not trust the list."""
        now = datetime.now()
        summaries = [
            FakePatternSummary("old", now - timedelta(days=400)),
            FakePatternSummary("future", now + timedelta(days=30)),
            FakePatternSummary("current", now - timedelta(days=5)),
        ]
        detail = FakePatternDetail(
            payee_working_pattern=FakePatternWithWeeks(
                working_weeks=[FakeWorkingWeek()]
            )
        )

        _, api = self._call(FakePatternsResponse(summaries), detail)

        self.assertEqual(
            api.get_employee_working_pattern.call_args.kwargs[
                "employee_working_pattern_id"
            ],
            "current",
        )

    def test_alternating_multi_week_pattern_returns_empty(self) -> None:
        """No single-week representation exists, so the caller seeds defaults."""
        summaries = [FakePatternSummary("p", datetime.now() - timedelta(days=1))]
        detail = FakePatternDetail(
            payee_working_pattern=FakePatternWithWeeks(
                working_weeks=[FakeWorkingWeek(), FakeWorkingWeek(monday=4.0)]
            )
        )

        result, _ = self._call(FakePatternsResponse(summaries), detail)

        self.assertEqual(result, [])

    def test_no_patterns_returns_empty(self) -> None:
        result, api = self._call(FakePatternsResponse(None))

        self.assertEqual(result, [])
        api.get_employee_working_pattern.assert_not_called()

    def test_only_future_dated_patterns_returns_empty(self) -> None:
        summaries = [FakePatternSummary("f", datetime.now() + timedelta(days=7))]

        result, api = self._call(FakePatternsResponse(summaries))

        self.assertEqual(result, [])
        api.get_employee_working_pattern.assert_not_called()


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

    def _import(self, dry_run: bool = True) -> Dict[str, Any]:
        employees = [
            self.current_employee,
            self.leaving_employee,
            self.departed_employee,
        ]
        # A realistic pattern, not []: the empty stub previously let these tests
        # pass over a function that could only raise.
        hours = [
            {
                "monday": 8.0,
                "tuesday": 8.0,
                "wednesday": 8.0,
                "thursday": 8.0,
                "friday": 6.0,
                "saturday": 0.0,
                "sunday": 0.0,
            }
        ]
        with (
            patch(f"{SYNC}.get_employees", return_value=employees),
            patch(
                f"{SYNC}.get_employee_salary_and_wages",
                return_value=[FakeSalaryAndWage()],
            ),
            patch(f"{SYNC}.get_employee_working_patterns", return_value=hours),
        ):
            return PayrollEmployeeSyncService.import_staff_from_xero(
                dry_run=dry_run,
                initial_password="import-test-password",
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

    def test_imported_staff_carry_the_xero_working_hours(self) -> None:
        """The point of reading the pattern at all: the new hire's roster
        expectation drives timesheet visibility and workshop capacity."""
        self._import(dry_run=False)

        staff = Staff.objects.get(email="current@example.com")
        self.assertEqual(float(staff.hours_mon), 8.0)
        self.assertEqual(float(staff.hours_fri), 6.0)
        self.assertEqual(float(staff.hours_sat), 0.0)
        self.assertEqual(staff.xero_user_id, self.current_employee.employee_id)


class CoerceXeroDateTests(BaseTestCase):
    """The shared normalizer is the contract the pattern selection depends on."""

    def test_datetime_becomes_date(self) -> None:
        self.assertEqual(
            coerce_xero_date(datetime(2026, 3, 4, 15, 30)), date(2026, 3, 4)
        )
