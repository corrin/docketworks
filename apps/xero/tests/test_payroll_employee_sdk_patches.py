"""The permanent Xero Payroll SDK compatibility patch copied from v1."""

from datetime import date

import pytest
from xero_python.payrollnz import Address, Employee, Employment, SalaryAndWage, TimesheetLine

from apps.xero import payroll_sdk  # noqa: F401 -- importing it is the behaviour under test


def _address() -> Address:
    return Address(
        address_line1="1 Molesworth Street",
        city="Wellington",
        post_code="6011",
        country_name="New Zealand",
    )


def test_the_seven_v1_response_fields_accept_none() -> None:
    employee = Employee(
        first_name="Demo", last_name="Contractor", address=_address(), date_of_birth=None
    )
    salary = SalaryAndWage(
        earnings_rate_id="rate-1",
        number_of_units_per_week=40.0,
        number_of_units_per_day=8.0,
        days_per_week=5,
        rate_per_unit=30.0,
        payment_type="Hourly",
        effective_from=date(2025, 4, 1),
        annual_salary=None,
        status=None,
    )
    employment = Employment(
        payroll_calendar_id="calendar-1",
        start_date=date(2025, 4, 1),
        engagement_type=None,
    )
    line = TimesheetLine(date=None, earnings_rate_id=None, number_of_units=None)

    assert employee.date_of_birth is None
    assert (salary.annual_salary, salary.status) == (None, None)
    assert employment.engagement_type is None
    assert (line.date, line.earnings_rate_id, line.number_of_units) == (None, None, None)


def test_unpatched_required_fields_still_validate() -> None:
    with pytest.raises(ValueError, match="first_name"):
        Employee(first_name=None, last_name="Silva", address=_address(), date_of_birth=None)
    with pytest.raises(ValueError, match="start_date"):
        Employment(payroll_calendar_id="calendar-1", start_date=None)
