"""The SDK null-tolerance window, and the guarantee that it stays shut.

Each relaxation exists because the SDK enforces a required field the live Xero
product legitimately leaves empty, and it enforces it on the way IN as well as
out — so one demo-organisation contractor record makes the whole employee list
undeserialisable.

What matters as much as the relaxation working is that it is NOT in force the
rest of the time: our own creation payloads are built outside the window
precisely so the SDK still validates them, and a permanently patched setter
would silently withdraw that check everywhere.
"""

from datetime import date

import pytest
from xero_python.payrollnz import Address, Employee, Employment, SalaryAndWage

from apps.xero.payroll_employees import (
    _EMPLOYEE_DOB,
    _EMPLOYMENT_ENGAGEMENT,
    _HOURLY_SALARY_GAPS,
    _sdk_null_tolerance,
)


def _address() -> Address:
    return Address(
        address_line1="1 Molesworth Street",
        city="Wellington",
        post_code="6011",
        country_name="New Zealand",
    )


def _salary(**overrides: object) -> SalaryAndWage:
    fields: dict[str, object] = {
        "earnings_rate_id": "rate-1",
        "number_of_units_per_week": 40.0,
        "number_of_units_per_day": 8.0,
        "days_per_week": 5,
        "rate_per_unit": 30.0,
        "payment_type": "Hourly",
        "effective_from": date(2025, 4, 1),
        "annual_salary": 0,
        "status": "Active",
    }
    return SalaryAndWage(**(fields | overrides))


class TestInsideTheWindow:
    """Xero's own records deserialise, however incomplete the SDK thinks they are."""

    def test_an_employee_with_no_date_of_birth_can_be_read(self) -> None:
        """Demo Company's contractors have none, and Xero refuses to accept one."""
        with _sdk_null_tolerance(_EMPLOYEE_DOB):
            employee = Employee(
                first_name="Demo", last_name="Contractor", address=_address(), date_of_birth=None
            )

        assert employee.date_of_birth is None

    def test_an_hourly_salary_record_needs_no_annual_salary_or_status(self) -> None:
        with _sdk_null_tolerance(_HOURLY_SALARY_GAPS):
            salary = _salary(annual_salary=None, status=None)

        assert (salary.annual_salary, salary.status) == (None, None)

    def test_an_employment_needs_no_engagement_type(self) -> None:
        with _sdk_null_tolerance(_EMPLOYMENT_ENGAGEMENT):
            employment = Employment(
                payroll_calendar_id="calendar-1",
                start_date=date(2025, 4, 1),
                engagement_type=None,
            )

        assert employment.engagement_type is None


class TestOutsideTheWindow:
    """The SDK's validation is back on, so our own payloads are still checked."""

    def test_an_employee_we_build_still_needs_a_date_of_birth(self) -> None:
        with pytest.raises(ValueError, match="date_of_birth"):
            Employee(first_name="Ana", last_name="Silva", address=_address(), date_of_birth=None)

    def test_a_salary_record_we_build_still_needs_annual_salary_and_status(self) -> None:
        with pytest.raises(ValueError, match="annual_salary"):
            _salary(annual_salary=None)
        with pytest.raises(ValueError, match="status"):
            _salary(status=None)

    def test_an_employment_outside_its_window_still_needs_an_engagement_type(self) -> None:
        """_create_employment opens a window for exactly this; nothing else may."""
        with pytest.raises(ValueError, match="engagement_type"):
            Employment(
                payroll_calendar_id="calendar-1",
                start_date=date(2025, 4, 1),
                engagement_type=None,
            )

    def test_a_window_relaxes_only_the_field_it_names(self) -> None:
        """The guarantee the per-call-site scoping exists to give."""
        with _sdk_null_tolerance(_EMPLOYMENT_ENGAGEMENT):
            # The employment window must not quietly excuse a missing date of
            # birth on an employee payload of ours.
            with pytest.raises(ValueError, match="date_of_birth"):
                Employee(
                    first_name="Ana", last_name="Silva", address=_address(), date_of_birth=None
                )
            # nor a start date on the very object it was opened for
            with pytest.raises(ValueError, match="start_date"):
                Employment(payroll_calendar_id="calendar-1", start_date=None)

        with _sdk_null_tolerance(_EMPLOYEE_DOB), pytest.raises(ValueError, match="annual_salary"):
            _salary(annual_salary=None)

    def test_a_failure_inside_the_window_still_closes_it(self) -> None:
        """A raising Xero call must not leave validation off for the process."""
        with pytest.raises(RuntimeError, match="xero exploded"), _sdk_null_tolerance(_EMPLOYEE_DOB):
            raise RuntimeError("xero exploded")

        with pytest.raises(ValueError, match="date_of_birth"):
            Employee(first_name="Ana", last_name="Silva", address=_address(), date_of_birth=None)

    def test_nesting_does_not_strand_the_relaxation(self) -> None:
        with _sdk_null_tolerance(_EMPLOYEE_DOB), _sdk_null_tolerance(_EMPLOYEE_DOB):
            pass

        with pytest.raises(ValueError, match="date_of_birth"):
            Employee(first_name="Ana", last_name="Silva", address=_address(), date_of_birth=None)
