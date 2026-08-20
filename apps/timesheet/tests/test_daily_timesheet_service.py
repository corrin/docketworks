"""Daily-timesheet behavior and query-count regression coverage.

The UI depends on who appears, the status ladder, alert wording, and batched
job-breakdown serialization.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.accounts.models import Staff
from apps.company.models import Company
from apps.company.tests.job_fixtures import make_job
from apps.core.models import CompanyDefaults
from apps.job.models import Job
from apps.timesheet.services import daily_timesheet_service
from apps.timesheet.tests.conftest import make_staff, make_time_line

pytestmark = pytest.mark.django_db

WEDNESDAY = date(2026, 5, 6)
SATURDAY = date(2026, 5, 9)


class TestStaffDailyRow:
    def test_totals_split_billable_and_non_billable(self, job: Job, worker: Staff) -> None:
        make_time_line(job, worker, accounting_date=WEDNESDAY, hours="5.000")
        make_time_line(job, worker, accounting_date=WEDNESDAY, hours="3.000", is_billable=False)

        row = daily_timesheet_service.get_staff_timesheet_data(worker, WEDNESDAY, False)

        assert row["actual_hours"] == 8.0
        assert row["billable_hours"] == 5.0
        assert row["non_billable_hours"] == 3.0
        assert row["total_revenue"] == pytest.approx(8 * 120.0)
        assert row["total_cost"] == pytest.approx(8 * 48.0)
        assert row["entry_count"] == 2

    def test_hour_percentages_are_divided_in_decimal(self, job: Job, worker: Staff) -> None:
        """Hour ratios use Decimal because float division differs in the last bits."""
        make_time_line(job, worker, accounting_date=WEDNESDAY, hours="1.000")
        make_time_line(job, worker, accounting_date=WEDNESDAY, hours="2.000", is_billable=False)

        row = daily_timesheet_service.get_staff_timesheet_data(worker, WEDNESDAY, False)

        assert row["billable_percentage"] == float(Decimal(1) / Decimal(3) * 100)
        assert row["billable_percentage"] != (1.0 / 3.0) * 100

    def test_status_ladder(self, job: Job, worker: Staff) -> None:
        # Scheduled 8h by default; 8h booked is Complete.
        make_time_line(job, worker, accounting_date=WEDNESDAY, hours="8.000")
        assert (
            daily_timesheet_service.get_staff_timesheet_data(worker, WEDNESDAY, False)["day_status"]
            == "Complete"
        )

    def test_no_entries_is_no_entry_with_an_alert(self, worker: Staff) -> None:
        row = daily_timesheet_service.get_staff_timesheet_data(worker, WEDNESDAY, False)
        assert row["day_status"] == "No Entry"
        assert row["alerts"] == ["No timesheet entries"]

    def test_short_day_is_partial_and_flags_low_hours(self, job: Job, worker: Staff) -> None:
        make_time_line(job, worker, accounting_date=WEDNESDAY, hours="2.000")

        row = daily_timesheet_service.get_staff_timesheet_data(worker, WEDNESDAY, False)

        assert row["day_status"] == "Partial"
        assert "Low hours recorded" in row["alerts"]

    def test_long_day_flags_overtime(self, job: Job, worker: Staff) -> None:
        make_time_line(job, worker, accounting_date=WEDNESDAY, hours="10.000")

        row = daily_timesheet_service.get_staff_timesheet_data(worker, WEDNESDAY, False)

        assert row["day_status"] == "Complete"
        assert "Overtime recorded" in row["alerts"]

    def test_an_unrostered_day_with_nothing_booked_is_off(self, worker: Staff) -> None:
        row = daily_timesheet_service.get_staff_timesheet_data(worker, SATURDAY, False)

        assert row["scheduled_hours"] == 0.0
        assert row["day_status"] == "Off"

    def test_hours_booked_on_an_unrostered_day_are_flagged_unscheduled(
        self, job: Job, worker: Staff
    ) -> None:
        """Saturday hours are visible even with weekend timesheets turned off.

        v1 reported this day as plain "Weekend" whenever the weekend flag was
        off, hiding the fact that someone had booked four hours on it.
        """
        make_time_line(job, worker, accounting_date=SATURDAY, hours="4.000")

        for weekend_enabled in (False, True):
            row = daily_timesheet_service.get_staff_timesheet_data(
                worker, SATURDAY, weekend_enabled
            )

            assert row["scheduled_hours"] == 0.0
            assert row["day_status"] == "Unscheduled"


class TestJobBreakdown:
    def test_breakdown_is_grouped_by_job_and_sorted_by_hours(
        self, job: Job, company: Company, superuser: Staff, worker: Staff
    ) -> None:
        second_job = make_job(company, superuser, name="Second Job")
        make_time_line(job, worker, accounting_date=WEDNESDAY, hours="2.000")
        make_time_line(second_job, worker, accounting_date=WEDNESDAY, hours="3.000")

        row = daily_timesheet_service.get_staff_timesheet_data(worker, WEDNESDAY, False)

        assert [(entry["job_name"], entry["hours"]) for entry in row["job_breakdown"]] == [
            ("Second Job", 3.0),
            ("Timesheet Job", 2.0),
        ]

    def test_breakdown_does_not_lazy_load_job_or_company(
        self, job: Job, company: Company, superuser: Staff, worker: Staff
    ) -> None:
        """Regression guard: the daily grid must not N+1 on job/company."""
        second_job = make_job(company, superuser, name="Second Job")
        make_time_line(job, worker, accounting_date=WEDNESDAY, hours="2.000")
        make_time_line(second_job, worker, accounting_date=WEDNESDAY, hours="3.000")

        with CaptureQueriesContext(connection) as captured:
            daily_timesheet_service.get_staff_timesheet_data(worker, WEDNESDAY, False)

        relation_queries = [
            query["sql"]
            for query in captured
            if 'FROM "job_costset"' in query["sql"]
            or 'FROM "job_job"' in query["sql"]
            or 'FROM "company_company"' in query["sql"]
        ]
        assert relation_queries == []


class TestDailySummary:
    def test_summary_totals_and_stats_across_staff(
        self, job: Job, worker: Staff, other_worker: Staff
    ) -> None:
        make_time_line(job, worker, accounting_date=WEDNESDAY, hours="8.000")
        make_time_line(job, other_worker, accounting_date=WEDNESDAY, hours="4.000")

        summary = daily_timesheet_service.get_daily_summary(WEDNESDAY)

        assert summary["date"] == WEDNESDAY.isoformat()
        totals = summary["daily_totals"]
        assert totals["total_actual_hours"] == 12.0
        assert totals["total_scheduled_hours"] == 16.0
        assert totals["missing_hours"] == 4.0
        stats = summary["summary_stats"]
        assert stats["total_staff"] == 2
        assert stats["complete_staff"] == 1
        assert stats["partial_staff"] == 1
        assert stats["completion_rate"] == 50.0

    def test_staff_without_a_payroll_id_are_hidden(self, job: Job, worker: Staff) -> None:
        """Regression guard: staff with no valid Xero payroll id never appear in timesheet views."""
        hidden = make_staff("hidden@example.com", xero_user_id="not-a-uuid")
        make_time_line(job, hidden, accounting_date=WEDNESDAY, hours="8.000")

        summary = daily_timesheet_service.get_daily_summary(WEDNESDAY)

        assert [row["staff_id"] for row in summary["staff_data"]] == [str(worker.id)]

    def test_staff_not_scheduled_that_day_are_excluded(self, worker: Staff) -> None:
        worker.hours_wed = Decimal("0.00")
        worker.save(update_fields=["hours_wed", "updated_at"])

        summary = daily_timesheet_service.get_daily_summary(WEDNESDAY)

        assert summary["staff_data"] == []

    def test_weekend_shows_staff_when_weekend_timesheets_are_enabled(self, worker: Staff) -> None:
        defaults = CompanyDefaults.get_solo()
        defaults.weekend_timesheets_enabled = True
        defaults.save(update_fields=["weekend_timesheets_enabled"])

        summary = daily_timesheet_service.get_daily_summary(SATURDAY)

        assert [row["staff_id"] for row in summary["staff_data"]] == [str(worker.id)]

    @pytest.mark.usefixtures("other_worker")
    def test_staff_daily_detail_returns_that_staff_row(self, job: Job, worker: Staff) -> None:
        make_time_line(job, worker, accounting_date=WEDNESDAY, hours="6.000")

        detail = daily_timesheet_service.get_staff_daily_detail(str(worker.id), WEDNESDAY)

        assert detail is not None
        assert detail["staff_id"] == str(worker.id)
        assert detail["actual_hours"] == 6.0

    @pytest.mark.usefixtures("worker")
    def test_staff_daily_detail_is_none_for_an_absent_staff_member(self) -> None:
        assert (
            daily_timesheet_service.get_staff_daily_detail(
                "00000000-0000-0000-0000-000000000000", WEDNESDAY
            )
            is None
        )
