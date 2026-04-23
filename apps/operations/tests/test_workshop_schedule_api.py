"""Tests for the workshop schedule API endpoints."""

from decimal import Decimal

from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import Staff
from apps.client.models import Client
from apps.job.models import Job
from apps.operations.services.scheduler_service import run_workshop_schedule
from apps.testing import BaseAPITestCase


def _make_staff(email_suffix):
    return Staff.objects.create_user(
        email=f"api-staff-{email_suffix}@test.example",
        password="testpass",
        first_name="Api",
        last_name=email_suffix,
        is_workshop_staff=True,
        hours_mon=Decimal("8"),
        hours_tue=Decimal("8"),
        hours_wed=Decimal("8"),
        hours_thu=Decimal("8"),
        hours_fri=Decimal("8"),
        hours_sat=Decimal("0"),
        hours_sun=Decimal("0"),
    )


def _make_job(client, staff, name="API Test Job", hours=8.0):
    job = Job.objects.create(
        client=client,
        name=name,
        status="approved",
        staff=staff,
    )
    summary = job.latest_estimate.summary or {}
    summary["hours"] = hours
    job.latest_estimate.summary = summary
    job.latest_estimate.save()
    return job


class WorkshopScheduleGetTests(BaseAPITestCase):
    """Tests for GET /api/operations/workshop-schedule/"""

    def setUp(self):
        self.client_obj = Client.objects.create(
            name="API Test Client",
            xero_last_modified=timezone.now(),
        )
        self.staff = _make_staff("a1")
        self.api_client = APIClient()
        self.api_client.force_authenticate(user=self.staff)
        self.url = reverse("operations:workshop-schedule")

    def test_no_run_returns_empty_response(self):
        """GET with no SchedulerRun returns empty lists."""
        response = self.api_client.get(self.url)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["days"], [])
        self.assertEqual(data["jobs"], [])
        self.assertEqual(data["unscheduled_jobs"], [])

    def test_get_returns_expected_shape(self):
        """GET returns 200 with days, jobs, and unscheduled_jobs keys."""
        _make_job(self.client_obj, self.test_staff)
        run_workshop_schedule()

        response = self.api_client.get(self.url)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("days", data)
        self.assertIn("jobs", data)
        self.assertIn("unscheduled_jobs", data)

    def test_scheduled_job_has_dates(self):
        """Scheduled jobs include anticipated_start_date and anticipated_end_date."""
        _make_job(self.client_obj, self.test_staff)
        run_workshop_schedule()

        response = self.api_client.get(self.url)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(len(data["jobs"]) > 0, "Expected at least one scheduled job")
        job = data["jobs"][0]
        self.assertIn("anticipated_start_date", job)
        self.assertIn("anticipated_end_date", job)

    def test_scheduled_job_has_people_fields(self):
        """Scheduled jobs include min_people, max_people, and assigned_staff."""
        _make_job(self.client_obj, self.test_staff)
        run_workshop_schedule()

        response = self.api_client.get(self.url)
        data = response.json()
        self.assertTrue(len(data["jobs"]) > 0)
        job = data["jobs"][0]
        self.assertIn("min_people", job)
        self.assertIn("max_people", job)
        self.assertIn("assigned_staff", job)

    def test_unscheduled_job_has_reason(self):
        """Unscheduled jobs include a machine-readable reason field."""
        # Job with no hours → unscheduled
        Job.objects.create(
            client=self.client_obj,
            name="No Hours Job",
            status="approved",
            staff=self.test_staff,
        )
        run_workshop_schedule()

        response = self.api_client.get(self.url)
        data = response.json()
        self.assertTrue(
            len(data["unscheduled_jobs"]) > 0,
            "Expected at least one unscheduled job",
        )
        unscheduled = data["unscheduled_jobs"][0]
        self.assertIn("reason", unscheduled)
        self.assertTrue(len(unscheduled["reason"]) > 0)

    def test_invalid_day_horizon_returns_400(self):
        """GET with day_horizon=0 returns 400."""
        response = self.api_client.get(self.url, {"day_horizon": 0})
        self.assertEqual(response.status_code, 400)


class WorkshopScheduleRecalculateTests(BaseAPITestCase):
    """Tests for POST /api/operations/workshop-schedule/recalculate/"""

    def setUp(self):
        self.client_obj = Client.objects.create(
            name="Recalc Test Client",
            xero_last_modified=timezone.now(),
        )
        self.staff = _make_staff("b1")
        self.api_client = APIClient()
        self.api_client.force_authenticate(user=self.staff)
        self.url = reverse("operations:workshop-schedule-recalculate")
        self.get_url = reverse("operations:workshop-schedule")

    def test_post_recalculate_returns_same_shape(self):
        """POST to recalculate returns 200 with days, jobs, unscheduled_jobs."""
        _make_job(self.client_obj, self.test_staff)

        response = self.api_client.post(self.url)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("days", data)
        self.assertIn("jobs", data)
        self.assertIn("unscheduled_jobs", data)
