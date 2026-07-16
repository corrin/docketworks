"""Tests for scheduler persistence: SchedulerRun, JobProjection, AllocationBlock."""

from datetime import date
from decimal import Decimal
from typing import cast
from unittest.mock import patch

from django.utils import timezone

from apps.accounts.models import Staff
from apps.company.models import Company
from apps.job.models import CostSet, Job, LabourSubtype
from apps.job.models.costing import CostLine
from apps.operations.models import AllocationBlock, JobProjection, SchedulerRun
from apps.operations.services.scheduler_service import run_workshop_schedule
from apps.testing import BaseTestCase


def _make_staff(email_suffix: str) -> Staff:
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


def _make_job(company: Company, staff: Staff, name: str = "Persist Test Job") -> Job:
    job = cast(
        Job,
        Job.objects.create(
            company=company,
            name=name,
            status="approved",
            staff=staff,
        ),
    )
    _set_workshop_hours(job.latest_estimate, 8.0)
    return job


class TestSchedulerRunRecord(BaseTestCase):
    """Verify SchedulerRun records are created correctly."""

    def setUp(self):
        self.client_obj = Company.objects.create(
            name="Persist Company",
            xero_last_modified=timezone.now(),
        )
        _make_staff("p1")
        _make_job(self.client_obj, self.test_staff)

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
        self.client_obj = Company.objects.create(
            name="Persist Company",
            xero_last_modified=timezone.now(),
        )
        _make_staff("p2")
        _make_job(self.client_obj, self.test_staff)

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
        self.client_obj = Company.objects.create(
            name="Persist Company",
            xero_last_modified=timezone.now(),
        )
        _make_staff("p3")

    def test_latest_forecast_from_latest_successful_run(self):
        """Two successful runs exist; the API reads data from the newer run."""
        job1 = _make_job(self.client_obj, self.test_staff, name="Job One")
        run_workshop_schedule()

        # Create a second job and run again
        job2 = _make_job(self.client_obj, self.test_staff, name="Job Two")
        second_run = run_workshop_schedule()

        # The second run is newer and should be returned by the view
        latest = SchedulerRun.objects.filter(succeeded=True).order_by("-ran_at").first()
        self.assertEqual(latest.id, second_run.id)

        # The second run should have projections for both jobs
        projections = JobProjection.objects.filter(scheduler_run=second_run)
        projected_job_ids = set(projections.values_list("job_id", flat=True))
        self.assertIn(job1.id, projected_job_ids)
        self.assertIn(job2.id, projected_job_ids)
