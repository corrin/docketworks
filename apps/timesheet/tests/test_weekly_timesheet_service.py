"""Behaviour tests for the weekly timesheet overview.

Ported from v1 ``apps/timesheet/tests/test_weekly_timesheet_service.py`` (the
annual-leave-loading cost split, the one behaviour that test asserted) plus the
payroll-column rules the weekly grid exists to produce.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.accounts.models import Staff
from apps.company.models import Company
from apps.company.tests.job_fixtures import make_job
from apps.core.models import CompanyDefaults
from apps.job.models import Job
from apps.timesheet.services import weekly_timesheet_service
from apps.timesheet.tests.conftest import WEEK_START, make_time_line

pytestmark = pytest.mark.django_db


def _leave_job(company: Company, superuser: Staff, leave_type: str) -> Job:
    """A leave job: name contains "Leave" and it carries the leave pay item."""
    from django.apps import apps as django_apps  # noqa: PLC0415

    job = make_job(company, superuser, name=leave_type)
    job.default_xero_pay_item = django_apps.get_model("xero", "XeroPayItem")._default_manager.get(
        name=leave_type, uses_leave_api=True
    )
    job.save(staff=superuser, update_fields=["default_xero_pay_item", "updated_at"])
    return job


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
        """v1 regression: weekly_cost carries the leave loading, base cost does not."""
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
        sick = _leave_job(company, superuser, "Sick Leave")
        annual = _leave_job(company, superuser, "Annual Leave")
        make_time_line(sick, worker, accounting_date=WEEK_START, hours="8.000")
        make_time_line(
            annual, worker, accounting_date=WEEK_START + timedelta(days=1), hours="4.000"
        )

        [row] = weekly_timesheet_service.get_weekly_overview(WEEK_START)["staff_data"]

        assert row["total_sick_leave_hours"] == 8.0
        assert row["total_annual_leave_hours"] == 4.0
        # Leave never counts as work, billed or unbilled.
        assert row["total_billed_hours"] == 0.0
        assert row["weekly_hours"][0]["status"] == "Leave"
        assert row["weekly_hours"][0]["leave_type"] == "Sick Leave"


class TestWeeklySummaries:
    def test_day_status_markers(self, job: Job, worker: Staff) -> None:
        make_time_line(job, worker, accounting_date=WEEK_START, hours="8.000")
        make_time_line(job, worker, accounting_date=WEEK_START + timedelta(days=1), hours="2.000")

        [row] = weekly_timesheet_service.get_weekly_overview(WEEK_START)["staff_data"]

        assert row["weekly_hours"][0]["status"] == "✓"  # met the schedule
        assert row["weekly_hours"][1]["status"] == "⚠"  # short
        assert row["weekly_hours"][2]["status"] == "⚠"  # nothing booked

    def test_staff_status_banding(self, job: Job, worker: Staff) -> None:
        for offset in range(3):
            make_time_line(
                job, worker, accounting_date=WEEK_START + timedelta(days=offset), hours="8.000"
            )

        overview = weekly_timesheet_service.get_weekly_overview(WEEK_START)
        [row] = overview["staff_data"]

        assert row["total_hours"] == 24.0
        assert row["status"] == "Partial"
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
