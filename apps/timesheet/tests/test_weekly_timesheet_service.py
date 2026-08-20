"""Weekly-timesheet behavior, including leave-loading and payroll columns."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.accounts.models import Staff
from apps.company.models import Company
from apps.core.models import CompanyDefaults
from apps.job.models import Job
from apps.timesheet.models import LeaveType
from apps.timesheet.services import daily_timesheet_service, weekly_timesheet_service
from apps.timesheet.tests.conftest import WEEK_START, make_leave_job, make_time_line

pytestmark = pytest.mark.django_db


@pytest.mark.usefixtures("worker")
class TestWeekShape:
    def test_five_day_week_by_default(self) -> None:
        overview = weekly_timesheet_service.get_weekly_overview(WEEK_START)

        assert overview["week_type"] == "5-day"
        assert overview["weekend_enabled"] is False
        assert len(overview["week_days"]) == 5
        assert overview["end_date"] == "2026-05-08"

    def test_seven_day_week_when_weekends_are_enabled(self) -> None:
        defaults = CompanyDefaults.get_solo()
        defaults.weekend_timesheets_enabled = True
        defaults.save(update_fields=["weekend_timesheets_enabled"])

        overview = weekly_timesheet_service.get_weekly_overview(WEEK_START)

        assert overview["week_type"] == "7-day"
        assert len(overview["week_days"]) == 7
        assert overview["end_date"] == "2026-05-10"

    def test_saturday_hours_appear_even_with_weekends_disabled(
        self, worker: Staff, job: Job
    ) -> None:
        """The screen a week is posted from must not hide hours that get posted.

        Opus: Posting covers Monday to Sunday whatever this flag says, so a five-day
        grid transmitted and paid Saturday hours that appeared in no column, in
        no total and in no summary. The reconciliation could not catch it
        either: it reads the same Mon-Sun window, so posted and recorded agreed
        and the panel reported a match.
        """
        saturday = WEEK_START + timedelta(days=5)
        make_time_line(job, worker, accounting_date=saturday, hours="6.000")

        overview = weekly_timesheet_service.get_weekly_overview(WEEK_START)

        assert len(overview["week_days"]) == 7, "a day carrying hours cannot be hidden"
        assert overview["week_days"][5] == "2026-05-09"
        [row] = [staff for staff in overview["staff_data"] if staff["staff_id"] == str(worker.id)]
        assert row["total_hours"] == Decimal("6.000")
        assert overview["weekly_summary"]["total_hours"] == Decimal("6.0")

    def test_a_rostered_saturday_agrees_with_the_daily_page(self, worker: Staff, job: Job) -> None:
        """One weekend rule, or the same booked day gets two different statuses.

        Opus: The daily service zeroes weekend scheduled hours when the flag is off;
        the weekly one read the roster straight off the model. That was
        harmless while this grid never rendered a weekend — the divergent path
        was unreachable — and went live the moment it started showing weekend
        days that carry hours. With a non-zero hours_sat and the flag off, the
        roster read would call 6h of 8 "Partial"; the shared rule calls it
        "Unscheduled", which is what the daily page says.
        """
        worker.hours_sat = Decimal("8.00")
        worker.save(update_fields=["hours_sat"])
        saturday = WEEK_START + timedelta(days=5)
        make_time_line(job, worker, accounting_date=saturday, hours="6.000")

        overview = weekly_timesheet_service.get_weekly_overview(WEEK_START)

        [row] = [staff for staff in overview["staff_data"] if staff["staff_id"] == str(worker.id)]
        [saturday_row] = [day for day in row["weekly_hours"] if day["day"] == "2026-05-09"]
        assert saturday_row["scheduled_hours"] == Decimal("0.0")
        assert saturday_row["day_status"] == "Unscheduled"

    def test_an_empty_weekend_stays_hidden(self, worker: Staff, job: Job) -> None:
        """The flag still earns its keep: it hides days, never hours."""
        make_time_line(job, worker, accounting_date=WEEK_START, hours="8.000")

        overview = weekly_timesheet_service.get_weekly_overview(WEEK_START)

        assert len(overview["week_days"]) == 5

    def test_navigation_points_at_the_neighbouring_weeks(self) -> None:
        overview = weekly_timesheet_service.get_weekly_overview(WEEK_START)

        assert overview["navigation"] == {
            "prev_week_date": "2026-04-27",
            "next_week_date": "2026-05-11",
            "current_week_date": "2026-05-04",
        }


class TestWeeklyCosts:
    def test_cash_and_loaded_costs_use_the_annual_leave_loading(
        self, job: Job, worker: Staff
    ) -> None:
        """Regression risk: weekly_cost carries the leave loading, base cost does not."""
        defaults = CompanyDefaults.get_solo()
        defaults.annual_leave_loading = Decimal("20.00")
        defaults.save(update_fields=["annual_leave_loading"])
        for offset in range(5):
            make_time_line(
                job,
                worker,
                accounting_date=WEEK_START + timedelta(days=offset),
                hours="8.000",
                unit_cost="38.00",
                unit_rev="0.00",
                is_billable=False,
            )

        overview = weekly_timesheet_service.get_weekly_overview(WEEK_START)
        [row] = overview["staff_data"]

        assert row["weekly_base_cost"] == 1520.00  # 5 * 8 * 38
        assert row["weekly_cost"] == 1824.00  # + 20%

    def test_loading_is_applied_to_the_rounded_base_cost(self, job: Job, worker: Staff) -> None:
        """v1 rounds the base to cents FIRST, so base * loading reconciles for operators.

        Worked example: a base of 100.005 rounds to 100.00 and loads to 120.00.
        Loading the unrounded sum instead yields 120.01, which does not reconcile
        against the 100.00 shown beside it.
        """
        defaults = CompanyDefaults.get_solo()
        defaults.annual_leave_loading = Decimal("20.00")
        defaults.save(update_fields=["annual_leave_loading"])
        make_time_line(job, worker, accounting_date=WEEK_START, hours="1.000", unit_cost="100.00")
        make_time_line(job, worker, accounting_date=WEEK_START, hours="0.001", unit_cost="5.00")

        [row] = weekly_timesheet_service.get_weekly_overview(WEEK_START)["staff_data"]
        [monday, *_] = row["weekly_hours"]

        assert monday["daily_base_cost"] == 100.00
        assert monday["daily_cost"] == 120.00


class TestPayrollColumns:
    def test_overtime_hours_land_in_their_own_columns(self, job: Job, worker: Staff) -> None:
        make_time_line(job, worker, accounting_date=WEEK_START, hours="8.000")
        make_time_line(
            job, worker, accounting_date=WEEK_START, hours="2.000", wage_rate_multiplier=1.5
        )
        make_time_line(
            job, worker, accounting_date=WEEK_START, hours="1.000", wage_rate_multiplier=2.0
        )

        [row] = weekly_timesheet_service.get_weekly_overview(WEEK_START)["staff_data"]

        assert row["total_overtime_1_5x_hours"] == 2.0
        assert row["total_overtime_2x_hours"] == 1.0
        assert row["total_overtime_hours"] == 3.0
        assert row["total_billed_hours"] == 11.0

    def test_unpaid_hours_are_posted_to_no_payroll_bucket(self, job: Job, worker: Staff) -> None:
        make_time_line(
            job, worker, accounting_date=WEEK_START, hours="4.000", wage_rate_multiplier=0.0
        )

        [row] = weekly_timesheet_service.get_weekly_overview(WEEK_START)["staff_data"]

        assert row["total_hours"] == 4.0
        assert row["total_billed_hours"] == 0.0
        assert row["total_unbilled_hours"] == 0.0

    def test_non_billable_work_is_unbilled_not_billed(self, job: Job, worker: Staff) -> None:
        make_time_line(job, worker, accounting_date=WEEK_START, hours="6.000", is_billable=False)

        [row] = weekly_timesheet_service.get_weekly_overview(WEEK_START)["staff_data"]

        assert row["total_unbilled_hours"] == 6.0
        assert row["total_billed_hours"] == 0.0
        assert row["total_billable_hours"] == 0.0

    def test_leave_hours_are_split_by_the_jobs_pay_item(
        self, company: Company, superuser: Staff, worker: Staff
    ) -> None:
        sick = make_leave_job(company, superuser, "Sick Leave")
        annual = make_leave_job(company, superuser, "Annual Leave")
        make_time_line(sick, worker, accounting_date=WEEK_START, hours="8.000")
        make_time_line(
            annual, worker, accounting_date=WEEK_START + timedelta(days=1), hours="4.000"
        )

        [row] = weekly_timesheet_service.get_weekly_overview(WEEK_START)["staff_data"]

        assert row["total_sick_leave_hours"] == 8.0
        assert row["total_annual_leave_hours"] == 4.0
        # Leave never counts as work, billed or unbilled.
        assert row["total_billed_hours"] == 0.0
        assert row["weekly_hours"][0]["day_status"] == "Leave"
        # Opus: The category CODE, not the Xero pay item's display name. An admin
        # can rename that item from the leave-settings screen, so putting the
        # name on the wire made a rename change what this screen said a day was.
        assert row["weekly_hours"][0]["leave_type"] == LeaveType.Code.SICK


class TestAgreementWithTheDailyOverview:
    """The two screens must answer the same question about a day the same way.

    Opus: This is the regression these renames exist to prevent: v1 let the weekly
    cell and the daily row drift apart until the same person on the same day
    read "Complete" on one screen and "⚠" on the other.
    """

    @pytest.mark.parametrize(
        ("hours", "expected"),
        [("8.000", "Complete"), ("2.000", "Partial")],
    )
    def test_the_weekly_cell_matches_the_daily_row(
        self, job: Job, worker: Staff, hours: str, expected: str
    ) -> None:
        make_time_line(job, worker, accounting_date=WEEK_START, hours=hours)

        [week_row] = weekly_timesheet_service.get_weekly_overview(WEEK_START)["staff_data"]
        day_row = daily_timesheet_service.get_staff_timesheet_data(worker, WEEK_START, False)

        assert week_row["weekly_hours"][0]["day_status"] == expected
        assert day_row["day_status"] == expected
        assert week_row["staff_name"] == day_row["staff_name"]
        assert week_row["weekly_hours"][0]["hours"] == day_row["actual_hours"]
        assert week_row["weekly_hours"][0]["billable_hours"] == day_row["billable_hours"]

    def test_both_screens_call_a_leave_day_leave(
        self, company: Company, superuser: Staff, worker: Staff
    ) -> None:
        """v1's daily screen called a leave day "Complete" — it saw hours and stopped asking."""
        sick = make_leave_job(company, superuser, "Sick Leave")
        make_time_line(sick, worker, accounting_date=WEEK_START, hours="8.000")

        [week_row] = weekly_timesheet_service.get_weekly_overview(WEEK_START)["staff_data"]
        day_row = daily_timesheet_service.get_staff_timesheet_data(worker, WEEK_START, False)

        assert week_row["weekly_hours"][0]["day_status"] == "Leave"
        assert day_row["day_status"] == "Leave"


class TestWeeklySummaries:
    def test_day_status_uses_the_same_words_as_the_daily_overview(
        self, job: Job, worker: Staff
    ) -> None:
        """A weekly cell is the daily status of that staff member on that day.

        v1 put the glyphs "✓" and "⚠" on the wire here while the daily screen
        put words on it, so the same day read two ways.
        """
        make_time_line(job, worker, accounting_date=WEEK_START, hours="8.000")
        make_time_line(job, worker, accounting_date=WEEK_START + timedelta(days=1), hours="2.000")

        [row] = weekly_timesheet_service.get_weekly_overview(WEEK_START)["staff_data"]

        assert row["weekly_hours"][0]["day_status"] == "Complete"
        assert row["weekly_hours"][1]["day_status"] == "Partial"
        assert row["weekly_hours"][2]["day_status"] == "No Entry"

    def test_staff_status_banding(self, job: Job, worker: Staff) -> None:
        for offset in range(3):
            make_time_line(
                job, worker, accounting_date=WEEK_START + timedelta(days=offset), hours="8.000"
            )

        overview = weekly_timesheet_service.get_weekly_overview(WEEK_START)
        [row] = overview["staff_data"]

        assert row["total_hours"] == 24.0
        assert row["week_status"] == "Partial"
        assert overview["summary_stats"]["partial_staff"] == 1
        assert overview["weekly_summary"]["staff_count"] == 1

    def test_job_metrics_report_actual_profit_for_the_week(self, job: Job, worker: Staff) -> None:
        make_time_line(job, worker, accounting_date=WEEK_START, hours="8.000")

        metrics = weekly_timesheet_service.get_weekly_overview(WEEK_START)["job_metrics"]

        # 8h at 120.00 revenue and 48.00 cost.
        assert metrics["total_actual_profit"] == pytest.approx(8 * (120.0 - 48.0))
        assert metrics["total_profit"] == metrics["total_actual_profit"]

    def test_lines_outside_the_week_are_ignored(self, job: Job, worker: Staff) -> None:
        make_time_line(job, worker, accounting_date=WEEK_START - timedelta(days=1), hours="8.000")

        [row] = weekly_timesheet_service.get_weekly_overview(WEEK_START)["staff_data"]

        assert row["total_hours"] == 0.0

    @pytest.mark.usefixtures("worker")
    def test_is_current_week_flags_this_week_only(self) -> None:
        today = timezone.localdate()
        this_monday = today - timedelta(days=today.weekday())

        assert weekly_timesheet_service.get_weekly_overview(this_monday)["is_current_week"] is True
        assert weekly_timesheet_service.get_weekly_overview(WEEK_START)["is_current_week"] is False
