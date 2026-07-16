"""Tests for the workshop schedule API endpoints."""

from datetime import date
from decimal import Decimal
from typing import cast

from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import Staff
from apps.company.models import Company
from apps.job.models import CostSet, Job, LabourSubtype
from apps.job.models.costing import CostLine
from apps.operations.services.scheduler_service import run_workshop_schedule
from apps.testing import BaseAPITestCase


def _make_staff(email_suffix: str) -> Staff:
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


def _set_workshop_hours(cost_set: CostSet, hours: float) -> None:
    """Create scheduler-visible workshop hours for a cost set."""
    summary = cost_set.summary or {}
    summary["hours"] = float(hours)
    cost_set.summary = summary
    cost_set.save()

    cost_set.cost_lines.filter(kind="time").delete()
    if Decimal(str(hours)) <= 0:
        return

    CostLine.objects.create(
        cost_set=cost_set,
        kind="time",
        labour_subtype=LabourSubtype.objects.get(name="Workshop"),
        desc="Workshop time",
        quantity=Decimal(str(hours)),
        unit_cost=Decimal("40.00"),
        unit_rev=Decimal("105.00"),
        accounting_date=date.today(),
    )


def _make_job(
    company: Company,
    staff: Staff,
    name: str = "API Test Job",
    hours: float = 8.0,
) -> Job:
    job = cast(
        Job,
        Job.objects.create(
            company=company,
            name=name,
            status="approved",
            staff=staff,
        ),
    )
    _set_workshop_hours(job.latest_estimate, hours)
    return job


class WorkshopScheduleGetTests(BaseAPITestCase):
    """Tests for GET /api/operations/workshop-schedule/"""

    def setUp(self):
        self.client_obj = Company.objects.create(
            name="API Test Company",
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
            company=self.client_obj,
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
        self.client_obj = Company.objects.create(
            name="Recalc Test Company",
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

    def test_post_recalculate_supports_quote_fallback_hours(self):
        """Jobs with no estimate hours still schedule from quote hours."""
        job = _make_job(self.client_obj, self.test_staff, hours=0.0)
        _set_workshop_hours(job.latest_quote, 8.0)

        response = self.api_client.post(self.url)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["unscheduled_jobs"], [])
        self.assertEqual(len(data["jobs"]), 1)
        self.assertEqual(data["jobs"][0]["id"], str(job.id))
