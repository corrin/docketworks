"""Tests for the queryset in JobsAPIView (GET /api/timesheets/jobs/).

Covers which jobs are selectable for time entry — specifically, that archived
fixed-price jobs are surfaced for a short window after archival so late time
can still be booked against them.
"""

from datetime import timedelta
from decimal import Decimal

from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import Staff
from apps.client.models import Client
from apps.job.models import Job
from apps.testing import BaseTestCase


class JobsAPIViewFilterTests(BaseTestCase):
    URL = "/api/timesheets/jobs/"

    def setUp(self) -> None:
        self.api = APIClient()
        self.superuser = Staff.objects.create_user(
            email="super@example.com",
            password="x",
            first_name="S",
            last_name="U",
            is_superuser=True,
            is_office_staff=True,
        )
        self.api.force_authenticate(user=self.superuser)
        self.test_client = Client.objects.create(
            name="Test Client",
            email="test@example.com",
            xero_last_modified="2024-01-01T00:00:00Z",
        )

    def _make_job(
        self,
        *,
        status: str,
        pricing_methodology: str = "time_materials",
        completed_at=None,
    ) -> Job:
        # Job.save() auto-generates job_number, so we can't set it here.
        job = Job.objects.create(
            name=f"Job {status} {pricing_methodology}",
            charge_out_rate=Decimal("100.00"),
            client=self.test_client,
            status=status,
            pricing_methodology=pricing_methodology,
        )
        if completed_at is not None:
            # completed_at is auto-set only on status *changes*, not on initial
            # create — bypass save() to avoid re-triggering change-event logic.
            Job.objects.filter(pk=job.pk).update(completed_at=completed_at)
        return job

    def _get_job_ids(self) -> set[str]:
        resp = self.api.get(self.URL)
        self.assertEqual(resp.status_code, 200, resp.content)
        return {j["id"] for j in resp.data["jobs"]}

    def test_active_jobs_included(self) -> None:
        in_progress = self._make_job(status="in_progress")
        recent = self._make_job(status="recently_completed")
        ids = self._get_job_ids()
        self.assertIn(str(in_progress.id), ids)
        self.assertIn(str(recent.id), ids)

    def test_archived_fixed_price_within_window_included(self) -> None:
        job = self._make_job(
            status="archived",
            pricing_methodology="fixed_price",
            completed_at=timezone.now() - timedelta(days=2),
        )
        self.assertIn(str(job.id), self._get_job_ids())

    def test_archived_fixed_price_outside_window_excluded(self) -> None:
        job = self._make_job(
            status="archived",
            pricing_methodology="fixed_price",
            completed_at=timezone.now() - timedelta(days=10),
        )
        self.assertNotIn(str(job.id), self._get_job_ids())

    def test_archived_time_materials_within_window_excluded(self) -> None:
        job = self._make_job(
            status="archived",
            pricing_methodology="time_materials",
            completed_at=timezone.now() - timedelta(days=2),
        )
        self.assertNotIn(str(job.id), self._get_job_ids())

    def test_archived_fixed_price_without_completed_at_excluded(self) -> None:
        job = self._make_job(
            status="archived",
            pricing_methodology="fixed_price",
            completed_at=None,
        )
        self.assertNotIn(str(job.id), self._get_job_ids())
