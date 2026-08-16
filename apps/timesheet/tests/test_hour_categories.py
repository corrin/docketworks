"""The vocabulary the daily and weekly timesheet reads share.

These assert the rules themselves; the two service test modules assert that
each screen reports them. Before this module the screens disagreed on all
three — leave identity, the billable rule, and the day-status words.
"""

from decimal import Decimal

import pytest

from apps.accounts.models import Staff
from apps.company.models import Company
from apps.company.tests.job_fixtures import make_job
from apps.job.models import Job
from apps.job.models.costing import CostLine
from apps.timesheet.services import hour_categories
from apps.timesheet.tests.conftest import WEEK_START, make_time_line

pytestmark = pytest.mark.django_db


class TestDayStatus:
    """The one day-status vocabulary: Leave, Off, Unscheduled, No Entry, Partial, Complete."""

    def test_leave_wins_over_every_other_signal(self) -> None:
        assert hour_categories.day_status(Decimal("0.0"), Decimal("8.0"), has_leave=True) == "Leave"
        assert hour_categories.day_status(Decimal("8.0"), Decimal("8.0"), has_leave=True) == "Leave"

    def test_a_day_nobody_was_rostered_for_is_off(self) -> None:
        assert hour_categories.day_status(Decimal("0.0"), Decimal("0.0"), has_leave=False) == "Off"

    def test_hours_booked_on_an_unrostered_day_are_unscheduled(self) -> None:
        """v1 called this "Weekend Work" on daily and "Off" on weekly.

        The same day, two answers.
        """
        assert (
            hour_categories.day_status(Decimal("6.0"), Decimal("0.0"), has_leave=False)
            == "Unscheduled"
        )

    def test_a_rostered_day_with_nothing_booked_is_no_entry(self) -> None:
        assert (
            hour_categories.day_status(Decimal("0.0"), Decimal("8.0"), has_leave=False)
            == "No Entry"
        )

    def test_short_of_the_roster_is_partial_and_meeting_it_is_complete(self) -> None:
        assert (
            hour_categories.day_status(Decimal("4.0"), Decimal("8.0"), has_leave=False) == "Partial"
        )
        assert (
            hour_categories.day_status(Decimal("7.9"), Decimal("8.0"), has_leave=False) == "Partial"
        )
        assert (
            hour_categories.day_status(Decimal("8.0"), Decimal("8.0"), has_leave=False)
            == "Complete"
        )
        assert (
            hour_categories.day_status(Decimal("9.0"), Decimal("8.0"), has_leave=False)
            == "Complete"
        )


class TestLineIdentity:
    def test_billable_and_the_multiplier_are_read_straight_off_the_line(
        self, job: Job, worker: Staff
    ) -> None:
        line = make_time_line(
            job, worker, accounting_date=WEEK_START, is_billable=False, wage_rate_multiplier=1.5
        )

        assert hour_categories.is_billable(line) is False
        assert hour_categories.wage_rate_multiplier(line) == Decimal("1.5")

    @pytest.mark.parametrize("key", ["is_billable", "wage_rate_multiplier"])
    def test_a_line_missing_a_denormalised_key_is_refused(
        self, job: Job, worker: Staff, key: str
    ) -> None:
        """Every timesheet write sets these, so absence is bad data, not a default.

        Defaulting would silently count an unpriced line as billable ordinary
        time and move the payroll totals with it (ADR 0015).
        """
        line = make_time_line(job, worker, accounting_date=WEEK_START)
        del line.meta[key]

        with pytest.raises(ValueError, match=key):
            hour_categories.categorise([line])

    def test_leave_is_read_from_the_lines_own_pay_item(
        self, company: Company, superuser: Staff, worker: Staff, leave_job: Job
    ) -> None:
        leave_line = make_time_line(leave_job, worker, accounting_date=WEEK_START)
        work_line = make_time_line(
            _work_job(company, superuser), worker, accounting_date=WEEK_START
        )

        assert hour_categories.is_leave(leave_line) is True
        assert hour_categories.is_leave(work_line) is False

    def test_a_line_with_no_pay_item_is_refused_rather_than_guessed(
        self, job: Job, worker: Staff
    ) -> None:
        """CostLine.clean requires the pay item on actual time lines, so absence is bad data.

        Guessing "not leave" would silently drop the hours out of the payroll
        columns while still counting them in the day total (ADR 0015).
        """
        line = make_time_line(job, worker, accounting_date=WEEK_START)
        line.xero_pay_item = None

        with pytest.raises(ValueError, match="xero_pay_item"):
            hour_categories.is_leave(line)


class TestCategorise:
    def test_the_customer_split_counts_every_line(self, job: Job, worker: Staff) -> None:
        """Billable is a charging question, so an unpaid line still bills the customer."""
        make_time_line(job, worker, accounting_date=WEEK_START, hours="6.000")
        make_time_line(job, worker, accounting_date=WEEK_START, hours="2.000", is_billable=False)
        lines = _lines_for(job)

        categories = hour_categories.categorise(lines)

        assert categories.billable == Decimal("6.000")
        assert categories.non_billable == Decimal("2.000")

    def test_the_payroll_split_drops_unpaid_lines(self, job: Job, worker: Staff) -> None:
        """A 0x multiplier is unpaid time: it belongs to neither payroll bucket."""
        make_time_line(
            job, worker, accounting_date=WEEK_START, hours="4.000", wage_rate_multiplier=0.0
        )

        categories = hour_categories.categorise(_lines_for(job))

        assert categories.billed == Decimal("0")
        assert categories.unbilled == Decimal("0")
        assert categories.billable == Decimal("4.000")

    def test_overtime_lands_in_its_own_bucket_and_still_counts_as_billed(
        self, job: Job, worker: Staff
    ) -> None:
        make_time_line(job, worker, accounting_date=WEEK_START, hours="8.000")
        make_time_line(
            job, worker, accounting_date=WEEK_START, hours="2.000", wage_rate_multiplier=1.5
        )
        make_time_line(
            job, worker, accounting_date=WEEK_START, hours="1.000", wage_rate_multiplier=2.0
        )

        categories = hour_categories.categorise(_lines_for(job))

        assert categories.overtime_1_5x == Decimal("2.000")
        assert categories.overtime_2x == Decimal("1.000")
        assert categories.billed == Decimal("11.000")

    def test_named_leave_types_get_their_own_columns(
        self, company: Company, superuser: Staff, worker: Staff
    ) -> None:
        sick = _leave_job(company, superuser, "Sick Leave")
        annual = _leave_job(company, superuser, "Annual Leave")
        make_time_line(sick, worker, accounting_date=WEEK_START, hours="8.000")
        make_time_line(annual, worker, accounting_date=WEEK_START, hours="4.000")

        categories = hour_categories.categorise(_lines_for(sick) + _lines_for(annual))

        assert categories.sick_leave == Decimal("8.000")
        assert categories.annual_leave == Decimal("4.000")
        # Leave is not worked time, so it reaches neither payroll work bucket.
        assert categories.billed == Decimal("0")
        assert categories.unbilled == Decimal("0")

    def test_unnamed_leave_types_land_in_other_leave_rather_than_vanishing(
        self, company: Company, superuser: Staff, worker: Staff
    ) -> None:
        """v1 reported three leave columns and silently dropped every other leave type.

        The hours still counted in the day total, so the columns did not sum to
        it and payroll reconciliation had an unexplained gap.
        """
        unpaid = _leave_job(company, superuser, "Unpaid Leave")
        make_time_line(unpaid, worker, accounting_date=WEEK_START, hours="7.500")

        categories = hour_categories.categorise(_lines_for(unpaid))

        assert categories.other_leave == Decimal("7.500")
        assert categories.sick_leave == Decimal("0")

    def test_leave_and_work_on_one_day_are_reported_separately(
        self, company: Company, superuser: Staff, worker: Staff, leave_job: Job
    ) -> None:
        work = _work_job(company, superuser)
        make_time_line(work, worker, accounting_date=WEEK_START, hours="4.000")
        make_time_line(leave_job, worker, accounting_date=WEEK_START, hours="4.000")

        categories = hour_categories.categorise(_lines_for(work) + _lines_for(leave_job))

        assert categories.billed == Decimal("4.000")
        assert categories.sick_leave == Decimal("4.000")


# --- helpers -------------------------------------------------------------


def _lines_for(job: Job) -> list[CostLine]:
    """The job's actual time lines, with the pay item joined as the services join it."""
    return list(
        CostLine.objects.filter(
            cost_set__job=job, cost_set__kind="actual", kind="time"
        ).select_related("xero_pay_item")
    )


def _work_job(company: Company, superuser: Staff) -> Job:
    return make_job(company, superuser, name="Ordinary Work")


def _leave_job(company: Company, superuser: Staff, pay_item_name: str) -> Job:
    """A job carrying a leave pay item, the shape leave bookings take."""
    from django.apps import apps as django_apps  # noqa: PLC0415

    job = make_job(company, superuser, name=pay_item_name)
    job.default_xero_pay_item = django_apps.get_model("xero", "XeroPayItem")._default_manager.get(
        name=pay_item_name, uses_leave_api=True
    )
    job.save(staff=superuser, update_fields=["default_xero_pay_item", "updated_at"])
    return job


@pytest.fixture
def leave_job(company: Company, superuser: Staff) -> Job:
    return _leave_job(company, superuser, "Sick Leave")
