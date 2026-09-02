"""Salaried payroll terms: the two paths that used to answer with a wrong number.

Opus: Both failures were silent. A salaried staff member with nothing synced from
Xero got the manual roster back, so the weekly grid showed plausible scheduled
hours for someone the costing pipeline refused outright. A working pattern
missing a weekday counted that day as zero hours, which shrank the divisor and
inflated the hourly cost every job booked against them is charged.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.accounts.models import Staff, StaffPayrollTerm
from apps.accounts.services.payroll_terms import (
    average_weekly_hours,
    contracted_hours_on,
    salary_cost_rate,
    salary_term_on,
)
from apps.core.models import CompanyDefaults

pytestmark = pytest.mark.django_db

WORK_DATE = date(2026, 8, 18)
#: Floats, like the Xero sync writes (``float(getattr(week, day) or 0)``).
FULL_WEEK: dict[str, float] = {
    "monday": 8.0,
    "tuesday": 8.0,
    "wednesday": 8.0,
    "thursday": 8.0,
    "friday": 8.0,
    "saturday": 0.0,
    "sunday": 0.0,
}


@pytest.fixture
def salaried() -> Staff:
    """A salaried staff member whose manual roster differs from any Xero pattern."""
    staff = Staff.objects.create_user(
        office_email="payroll-terms-salaried@example.com",
        password="s3cret-Pass!",
        first_name="Sally",
        last_name="Salaried",
    )
    staff.pay_basis = "salary"
    staff.hours_tue = Decimal("6.5")
    staff.save(update_fields=["pay_basis", "hours_tue", "updated_at"])
    return staff


@pytest.fixture
def hourly() -> Staff:
    """An hourly staff member, who needs no Xero terms to be schedulable."""
    staff = Staff.objects.create_user(
        office_email="payroll-terms-hourly@example.com",
        password="s3cret-Pass!",
        first_name="Harry",
        last_name="Hourly",
    )
    staff.hours_tue = Decimal("7.5")
    staff.save(update_fields=["hours_tue", "updated_at"])
    return staff


def _term(staff: Staff, weeks: list[dict[str, float]]) -> StaffPayrollTerm:
    return StaffPayrollTerm.objects.create(
        staff=staff,
        effective_from=date(2026, 1, 5),
        pay_basis="salary",
        annual_salary=Decimal("104000.00"),
        working_weeks=weeks,
    )


class TestUnsyncedSalariedStaff:
    def test_contracted_hours_refuse_rather_than_read_the_manual_roster(
        self, salaried: Staff
    ) -> None:
        """The grid showed 6.5h for someone no time could be booked against.

        Opus: ``salary_cost_rate`` already refused this staff member, so the two
        surfaces disagreed about whether they were usable at all.
        """
        with pytest.raises(ValidationError, match="not synced from Xero"):
            contracted_hours_on(salaried, WORK_DATE)

    def test_the_roster_still_answers_for_an_hourly_staff_member(self, hourly: Staff) -> None:
        """Only SALARIED staff need Xero terms; hourly staff keep their roster."""
        assert contracted_hours_on(hourly, WORK_DATE) == Decimal("7.5")

    def test_a_day_the_terms_record_as_hourly_reads_the_roster(self, salaried: Staff) -> None:
        """Pay basis is effective-dated: today's salary says nothing about last year."""
        StaffPayrollTerm.objects.create(
            staff=salaried,
            effective_from=date(2026, 1, 5),
            pay_basis="hourly",
            hourly_rate=Decimal("40.00"),
            working_weeks=[FULL_WEEK],
        )

        assert contracted_hours_on(salaried, WORK_DATE) == salaried.get_scheduled_hours(WORK_DATE)

    def test_salary_term_on_names_the_staff_member_and_the_fix(self, salaried: Staff) -> None:
        with pytest.raises(ValidationError, match="Sally Salaried"):
            salary_term_on(salaried, WORK_DATE)


class TestWorkingPatternCompleteness:
    def test_a_missing_weekday_is_refused_by_both_readers(self, salaried: Staff) -> None:
        """It used to raise in one reader and count as zero hours in the other."""
        partial = {day: hours for day, hours in FULL_WEEK.items() if day != "friday"}
        term = _term(salaried, [partial])

        with pytest.raises(ValidationError, match="missing friday"):
            average_weekly_hours(term)
        with pytest.raises(ValidationError, match="missing friday"):
            contracted_hours_on(salaried, WORK_DATE)

    def test_a_missing_weekday_used_to_inflate_the_hourly_cost_by_a_quarter(
        self, salaried: Staff
    ) -> None:
        """The regression, pinned as a number.

        Opus: $104,000 / 52 / 40h is $50.00, and 20% labour cost loading makes $60.00. With
        Friday's 8h defaulted to zero the divisor became 32h, giving $62.50 and
        a charged rate of $75.00 — a quarter over, on every hour booked.
        """
        CompanyDefaults.objects.update(labour_cost_loading=Decimal("20.00"))
        complete = _term(salaried, [FULL_WEEK])

        assert salary_cost_rate(complete) == Decimal("60.00")

        complete.working_weeks = [{d: h for d, h in FULL_WEEK.items() if d != "friday"}]
        complete.save(update_fields=["working_weeks"])

        with pytest.raises(ValidationError, match="missing friday"):
            salary_cost_rate(complete)

    def test_a_day_rostered_as_zero_is_ordinary_data(self, salaried: Staff) -> None:
        """A present zero is a non-working day; only an ABSENT key is bad data."""
        term = _term(salaried, [FULL_WEEK])

        assert average_weekly_hours(term) == Decimal("40")
        assert contracted_hours_on(salaried, date(2026, 8, 22)) == Decimal("0")  # a Saturday
