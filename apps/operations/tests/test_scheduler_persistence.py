"""Tests for scheduler persistence: SchedulerRun, JobProjection, AllocationBlock."""

from decimal import Decimal
from unittest.mock import patch

from django.utils import timezone

from apps.accounts.models import Staff
from apps.client.models import Client
from apps.job.models import Job
from apps.operations.models import AllocationBlock, JobProjection, SchedulerRun
from apps.operations.services.scheduler_service import run_workshop_schedule
from apps.testing import BaseTestCase


def _make_staff(email_suffix):
    return Staff.objects.create_user(
        email=f"staff-{email_suffix}@persist.example",
        password="testpass",
        first_name="Worker",
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


def _make_job(client, name="Persist Test Job"):
    job = Job.objects.create(
        client=client,
        name=name,
        status="approved",
    )
    # Set estimate hours so the job gets scheduled
    summary = job.latest_estimate.summary or {}
    summary["hours"] = 8.0
    job.latest_estimate.summary = summary
    job.latest_estimate.save()
    return job


class TestSchedulerRunRecord(BaseTestCase):
    """Verify SchedulerRun records are created correctly."""

    def setUp(self):
        self.client_obj = Client.objects.create(
            name="Persist Client",
            xero_last_modified=timezone.now(),
        )
        _make_staff("p1")
        _make_job(self.client_obj)

    def test_successful_run_creates_scheduler_run_record(self):
        """A successful run creates exactly one SchedulerRun record."""
        run_workshop_schedule()
        self.assertEqual(SchedulerRun.objects.count(), 1)

    def test_successful_run_creates_job_projections(self):
        """A successful run creates JobProjection records."""
        run = run_workshop_schedule()
        self.assertTrue(JobProjection.objects.filter(scheduler_run=run).exists())

    def test_successful_run_creates_allocation_blocks(self):
        """A successful run creates AllocationBlock records."""
        run = run_workshop_schedule()
        self.assertTrue(AllocationBlock.objects.filter(scheduler_run=run).exists())


class TestFailedRunPreservesData(BaseTestCase):
    """Verify a failed run does not overwrite good data from a previous run."""

    def setUp(self):
        self.client_obj = Client.objects.create(
            name="Persist Client",
            xero_last_modified=timezone.now(),
        )
        _make_staff("p2")
        _make_job(self.client_obj)

    def test_failed_run_preserves_last_successful(self):
        """After a failed run, the previously successful SchedulerRun still exists."""
        # First successful run
        first_run = run_workshop_schedule()
        self.assertEqual(SchedulerRun.objects.filter(succeeded=True).count(), 1)

        # Simulate a failure on the second run
        with patch(
            "apps.operations.services.scheduler_service._persist_results",
            side_effect=RuntimeError("simulated failure"),
        ):
            try:
                run_workshop_schedule()
            except RuntimeError:
                pass

        # Original successful run still present
        self.assertTrue(SchedulerRun.objects.filter(id=first_run.id).exists())

    def test_failed_run_does_not_overwrite_good_data(self):
        """Old projections still exist after a failed run attempt."""
        first_run = run_workshop_schedule()
        original_projection_count = JobProjection.objects.filter(
            scheduler_run=first_run
        ).count()
        self.assertGreater(original_projection_count, 0)

        with patch(
            "apps.operations.services.scheduler_service._persist_results",
            side_effect=RuntimeError("simulated failure"),
        ):
            try:
                run_workshop_schedule()
            except RuntimeError:
                pass

        # Projections from first run are untouched
        self.assertEqual(
            JobProjection.objects.filter(scheduler_run=first_run).count(),
            original_projection_count,
        )


class TestLatestForecastReadsNewestRun(BaseTestCase):
    """Verify the API reads from the most recent successful SchedulerRun."""

    def setUp(self):
        self.client_obj = Client.objects.create(
            name="Persist Client",
            xero_last_modified=timezone.now(),
        )
        _make_staff("p3")

    def test_latest_forecast_from_latest_successful_run(self):
        """Two successful runs exist; the API reads data from the newer run."""
        job1 = _make_job(self.client_obj, name="Job One")
        run_workshop_schedule()

        # Create a second job and run again
        job2 = _make_job(self.client_obj, name="Job Two")
        second_run = run_workshop_schedule()

        # The second run is newer and should be returned by the view
        latest = SchedulerRun.objects.filter(succeeded=True).order_by("-ran_at").first()
        self.assertEqual(latest.id, second_run.id)

        # The second run should have projections for both jobs
        projections = JobProjection.objects.filter(scheduler_run=second_run)
        projected_job_ids = set(projections.values_list("job_id", flat=True))
        self.assertIn(job1.id, projected_job_ids)
        self.assertIn(job2.id, projected_job_ids)
