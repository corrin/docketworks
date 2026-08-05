"""API tests for the /api/timesheets/ management surface (django test Client).

Covers the auth split (superuser only, NOT office staff) and the wire contract
of the daily, weekly, staff, and job endpoints.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.test import Client
from django.utils import timezone

from apps.accounts.models import Staff
from apps.company.models import Company
from apps.company.tests.job_fixtures import make_job
from apps.job.models import Job
from apps.timesheet.tests.conftest import (
    WEEK_START,
    authenticated_client,
    make_staff,
    make_time_line,
)

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.urls("apps.timesheet.tests.urls"),
]

WEDNESDAY = WEEK_START + timedelta(days=2)

MANAGEMENT_ENDPOINTS = (
    ("get", "/api/timesheets/daily/2026-05-06/"),
    ("get", "/api/timesheets/staff/"),
    ("get", "/api/timesheets/jobs/"),
    ("get", "/api/timesheets/weekly/"),
    ("get", "/api/timesheets/payroll/pay-runs/"),
    ("post", "/api/timesheets/payroll/pay-runs/create"),
    ("post", "/api/timesheets/payroll/pay-runs/refresh"),
    ("post", "/api/timesheets/payroll/post-staff-week/"),
)


class TestManagementSurfaceAuth:
    @pytest.mark.parametrize(("method", "url"), MANAGEMENT_ENDPOINTS)
    def test_office_staff_are_not_enough(self, office_staff: Staff, method: str, url: str) -> None:
        """Timesheet management requires superuser, not merely office-staff access."""
        client = authenticated_client(office_staff)
        response = getattr(client, method)(url, data={}, content_type="application/json")
        assert response.status_code == 403

    @pytest.mark.parametrize(("method", "url"), MANAGEMENT_ENDPOINTS)
    def test_anonymous_is_rejected(self, method: str, url: str) -> None:
        response = getattr(Client(), method)(url, data={}, content_type="application/json")
        assert response.status_code == 401

    def test_workshop_staff_are_not_enough(self, worker: Staff) -> None:
        response = authenticated_client(worker).get("/api/timesheets/weekly/")
        assert response.status_code == 403

    @pytest.mark.usefixtures("worker")
    def test_superuser_is_allowed(self, manage_client: Client) -> None:
        assert manage_client.get("/api/timesheets/weekly/").status_code == 200


class TestDailyEndpoints:
    def test_daily_summary_shape(self, manage_client: Client, job: Job, worker: Staff) -> None:
        make_time_line(job, worker, accounting_date=WEDNESDAY, hours="6.000")

        response = manage_client.get(f"/api/timesheets/daily/{WEDNESDAY.isoformat()}/")

        assert response.status_code == 200
        body = response.json()
        assert body["date"] == WEDNESDAY.isoformat()
        [row] = body["staff_data"]
        assert row["staff_name"] == "Wendy Workshop"
        assert row["staff_initials"] == "WW"
        assert row["actual_hours"] == 6.0
        assert body["daily_totals"]["total_actual_hours"] == 6.0
        assert body["summary_stats"]["total_staff"] == 1

    def test_daily_summary_rejects_a_bad_date(self, manage_client: Client) -> None:
        response = manage_client.get("/api/timesheets/daily/06-05-2026/")
        assert response.status_code == 400
        assert response.json()["detail"] == "Invalid date format. Use YYYY-MM-DD"

    def test_staff_daily_detail(self, manage_client: Client, job: Job, worker: Staff) -> None:
        make_time_line(job, worker, accounting_date=WEDNESDAY, hours="3.000")

        response = manage_client.get(
            f"/api/timesheets/staff/{worker.id}/daily/{WEDNESDAY.isoformat()}/"
        )

        assert response.status_code == 200
        body = response.json()
        assert body["staff_id"] == str(worker.id)
        assert body["actual_hours"] == 3.0
        assert body["job_breakdown"][0]["job_name"] == "Timesheet Job"

    @pytest.mark.usefixtures("worker")
    def test_staff_daily_detail_is_404_for_an_unknown_staff_member(
        self, manage_client: Client
    ) -> None:
        response = manage_client.get(
            f"/api/timesheets/staff/00000000-0000-0000-0000-000000000000/daily/"
            f"{WEDNESDAY.isoformat()}/"
        )
        assert response.status_code == 404


class TestWeeklyEndpoint:
    @pytest.mark.usefixtures("worker")
    def test_defaults_to_the_current_week(self, manage_client: Client) -> None:
        today = timezone.localdate()
        monday = today - timedelta(days=today.weekday())

        response = manage_client.get("/api/timesheets/weekly/")

        assert response.status_code == 200
        body = response.json()
        assert body["start_date"] == monday.isoformat()
        assert body["is_current_week"] is True
        assert body["export_mode"] == "payroll"

    @pytest.mark.usefixtures("worker")
    def test_explicit_start_date(self, manage_client: Client) -> None:
        response = manage_client.get(f"/api/timesheets/weekly/?start_date={WEEK_START.isoformat()}")

        assert response.status_code == 200
        assert response.json()["start_date"] == WEEK_START.isoformat()

    def test_bad_start_date_is_400(self, manage_client: Client) -> None:
        response = manage_client.get("/api/timesheets/weekly/?start_date=nonsense")
        assert response.status_code == 400


class TestStaffListEndpoint:
    def test_lists_displayable_staff_with_wage_rates(
        self, manage_client: Client, worker: Staff
    ) -> None:
        response = manage_client.get(f"/api/timesheets/staff/?date={WEDNESDAY.isoformat()}")

        assert response.status_code == 200
        body = response.json()
        assert body["total_count"] == 1
        [entry] = body["staff"]
        assert entry["id"] == str(worker.id)
        assert entry["firstName"] == "Wendy"
        assert entry["lastName"] == "Workshop"
        assert Decimal(str(entry["wageRate"])) == Decimal("48.00")
        assert entry["icon_url"] is None

    def test_staff_without_a_payroll_id_are_excluded(
        self, manage_client: Client, worker: Staff
    ) -> None:
        make_staff("no-payroll@example.com", xero_user_id="not-a-uuid")

        body = manage_client.get("/api/timesheets/staff/").json()

        assert [entry["id"] for entry in body["staff"]] == [str(worker.id)]

    def test_staff_who_left_before_the_date_are_excluded(
        self, manage_client: Client, worker: Staff
    ) -> None:
        leaver = make_staff("leaver@example.com", first_name="Lee", last_name="Aver")
        leaver.date_left = WEDNESDAY - timedelta(days=1)
        leaver.save(update_fields=["date_left", "updated_at"])

        body = manage_client.get(f"/api/timesheets/staff/?date={WEDNESDAY.isoformat()}").json()

        assert [entry["id"] for entry in body["staff"]] == [str(worker.id)]


class TestJobsListEndpoint:
    def test_active_jobs_are_selectable(self, manage_client: Client, job: Job) -> None:
        response = manage_client.get("/api/timesheets/jobs/")

        assert response.status_code == 200
        body = response.json()
        assert [entry["id"] for entry in body["jobs"]] == [str(job.id)]
        entry = body["jobs"][0]
        assert entry["company_name"] == "Timesheet Test Company"
        assert entry["has_actual_costset"] is True
        assert entry["default_xero_pay_item_name"] == "Ordinary Time"
        assert entry["shop_job"] is False
        rates = {
            rate["labour_subtype_name"]: rate["charge_out_rate"] for rate in entry["labour_rates"]
        }
        assert Decimal(str(rates["Workshop"])) == Decimal("120.00")

    def _archive(self, job: Job, *, methodology: str, days_ago: int | None) -> None:
        completed_at = timezone.now() - timedelta(days=days_ago) if days_ago is not None else None
        # untracked_update: bookkeeping only, no JobEvents wanted here.
        Job.objects.filter(pk=job.pk).untracked_update(
            status="archived", pricing_methodology=methodology, completed_at=completed_at
        )

    def test_recently_archived_fixed_price_jobs_stay_selectable(
        self, manage_client: Client, job: Job
    ) -> None:
        """Late time can still be booked to a fixed-price job for one week."""
        self._archive(job, methodology="fixed_price", days_ago=2)

        body = manage_client.get("/api/timesheets/jobs/").json()

        assert [entry["id"] for entry in body["jobs"]] == [str(job.id)]

    def test_long_archived_fixed_price_jobs_drop_out(self, manage_client: Client, job: Job) -> None:
        self._archive(job, methodology="fixed_price", days_ago=10)

        assert manage_client.get("/api/timesheets/jobs/").json()["jobs"] == []

    def test_archived_time_and_materials_jobs_drop_out_immediately(
        self, manage_client: Client, job: Job
    ) -> None:
        self._archive(job, methodology="time_materials", days_ago=2)

        assert manage_client.get("/api/timesheets/jobs/").json()["jobs"] == []

    def test_leave_jobs_expose_their_leave_type(
        self, manage_client: Client, company: Company, superuser: Staff
    ) -> None:
        from django.apps import apps as django_apps  # noqa: PLC0415

        leave_job = make_job(company, superuser, name="Annual Leave")
        leave_job.default_xero_pay_item = django_apps.get_model(
            "xero", "XeroPayItem"
        )._default_manager.get(name="Annual Leave", uses_leave_api=True)
        leave_job.save(staff=superuser, update_fields=["default_xero_pay_item", "updated_at"])

        body = manage_client.get("/api/timesheets/jobs/").json()

        entry = next(item for item in body["jobs"] if item["id"] == str(leave_job.id))
        assert entry["leave_type"] == "Annual Leave"
