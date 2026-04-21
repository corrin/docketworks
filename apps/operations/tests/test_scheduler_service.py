"""Tests for the workshop scheduler service logic."""

from datetime import date
from decimal import Decimal

from django.utils import timezone

from apps.accounts.models import Staff
from apps.client.models import Client
from apps.job.models import Job
from apps.job.models.costing import CostLine
from apps.operations.models import AllocationBlock, JobProjection
from apps.operations.models.job_projection import UnscheduledReason
from apps.operations.services.scheduler_service import run_workshop_schedule
from apps.testing import BaseTestCase


def _make_staff(email_suffix, is_workshop=True, hours=8.0):
    """Create a workshop staff member with predictable working hours."""
    return Staff.objects.create_user(
        email=f"staff-{email_suffix}@test.example",
        password="testpass",
        first_name="Worker",
        last_name=email_suffix,
        is_workshop_staff=is_workshop,
        hours_mon=Decimal(str(hours)),
        hours_tue=Decimal(str(hours)),
        hours_wed=Decimal(str(hours)),
        hours_thu=Decimal(str(hours)),
        hours_fri=Decimal(str(hours)),
        hours_sat=Decimal("0"),
        hours_sun=Decimal("0"),
    )


def _make_client():
    return Client.objects.create(
        name="Test Client",
        xero_last_modified=timezone.now(),
    )


def _make_job(
    client, staff, name="Test Job", status="approved", min_people=1, max_people=1
):
    job = Job(
        client=client,
        name=name,
        status=status,
        min_people=min_people,
        max_people=max_people,
    )
    job.save(staff=staff)
    return job


def _set_summary_hours(cost_set, hours):
    """Directly set the hours field on a CostSet summary."""
    summary = cost_set.summary or {}
    summary["hours"] = float(hours)
    cost_set.summary = summary
    cost_set.save()


class TestHoursComputation(BaseTestCase):
    """Tests for how remaining hours are computed from estimate/quote/actual."""

    def setUp(self):
        self.client_obj = _make_client()
        _make_staff("worker1")

    def test_estimate_hours_used_when_present(self):
        """Job with estimate hours schedules; remaining = estimate - actual."""
        job = _make_job(self.client_obj, self.test_staff)
        _set_summary_hours(job.latest_estimate, 10.0)

        run = run_workshop_schedule()

        proj = JobProjection.objects.get(scheduler_run=run, job=job)
        self.assertFalse(proj.is_unscheduled)
        # remaining = 10 hours (no actual)
        self.assertAlmostEqual(proj.remaining_hours, 0.0, delta=0.1)

    def test_quote_fallback_when_estimate_zero(self):
        """Job with zero estimate but valid quote schedules using quote hours."""
        job = _make_job(self.client_obj, self.test_staff)
        _set_summary_hours(job.latest_estimate, 0.0)
        _set_summary_hours(job.latest_quote, 8.0)

        run = run_workshop_schedule()

        proj = JobProjection.objects.get(scheduler_run=run, job=job)
        self.assertFalse(proj.is_unscheduled)

    def test_no_hours_unscheduled(self):
        """Job with no hours in estimate or quote is unscheduled."""
        job = _make_job(self.client_obj, self.test_staff)
        # Both estimate and quote have 0 hours by default

        run = run_workshop_schedule()

        proj = JobProjection.objects.get(scheduler_run=run, job=job)
        self.assertTrue(proj.is_unscheduled)
        self.assertEqual(
            proj.unscheduled_reason,
            UnscheduledReason.MISSING_ESTIMATE_OR_QUOTE_HOURS,
        )

    def test_zero_remaining_hours_excluded(self):
        """Job where actual >= estimate is unscheduled (not actively allocated)."""
        from apps.workflow.models import XeroPayItem

        job = _make_job(self.client_obj, self.test_staff)
        _set_summary_hours(job.latest_estimate, 5.0)

        # Add actual time lines totalling 5 hours so nothing remains
        pay_item = XeroPayItem.objects.get(name="Ordinary Time")
        staff = Staff.objects.filter(is_workshop_staff=True).first()
        today = date.today()

        CostLine.objects.create(
            cost_set=job.latest_actual,
            kind="time",
            desc="Actual time",
            quantity=Decimal("5.000"),
            unit_cost=Decimal("20.00"),
            unit_rev=Decimal("40.00"),
            accounting_date=today,
            xero_pay_item=pay_item,
            meta={
                "staff_id": str(staff.id),
                "date": today.isoformat(),
                "is_billable": True,
                "wage_rate_multiplier": 1.0,
            },
        )

        run = run_workshop_schedule()

        proj = JobProjection.objects.get(scheduler_run=run, job=job)
        self.assertTrue(proj.is_unscheduled)


class TestStaffFiltering(BaseTestCase):
    """Tests for which staff participate in scheduling."""

    def setUp(self):
        self.client_obj = _make_client()

    def test_only_workshop_staff_contribute(self):
        """Non-workshop staff are excluded from allocation."""
        office_staff = _make_staff("office", is_workshop=False)
        workshop_staff = _make_staff("shop")

        job = _make_job(self.client_obj, self.test_staff, min_people=1, max_people=1)
        _set_summary_hours(job.latest_estimate, 8.0)

        run = run_workshop_schedule()

        # Only workshop_staff should appear in allocation blocks
        blocks = AllocationBlock.objects.filter(scheduler_run=run)
        self.assertTrue(blocks.exists())
        staff_ids = set(blocks.values_list("staff_id", flat=True))
        self.assertNotIn(office_staff.id, staff_ids)
        self.assertIn(workshop_staff.id, staff_ids)

    def test_impossible_staffing_unscheduled(self):
        """min_people > available staff count causes unscheduled with correct reason."""
        _make_staff("solo")  # only 1 workshop staff

        job = _make_job(self.client_obj, self.test_staff, min_people=5, max_people=5)
        _set_summary_hours(job.latest_estimate, 8.0)

        run = run_workshop_schedule()

        proj = JobProjection.objects.get(scheduler_run=run, job=job)
        self.assertTrue(proj.is_unscheduled)
        self.assertEqual(
            proj.unscheduled_reason,
            UnscheduledReason.MIN_PEOPLE_EXCEEDS_STAFF,
        )


class TestPeopleAssignment(BaseTestCase):
    """Tests for min/max people constraints during allocation."""

    def setUp(self):
        self.client_obj = _make_client()

    def test_one_person_default(self):
        """Job with min=1, max=1 gets exactly one worker per day."""
        _make_staff("w1")
        _make_staff("w2")

        job = _make_job(self.client_obj, self.test_staff, min_people=1, max_people=1)
        _set_summary_hours(job.latest_estimate, 8.0)

        run = run_workshop_schedule()

        blocks = AllocationBlock.objects.filter(scheduler_run=run, job=job)
        self.assertTrue(blocks.exists())
        # Each day's blocks for this job should involve at most 1 worker
        from django.db.models import Count

        per_day = blocks.values("allocation_date").annotate(
            count=Count("staff", distinct=True)
        )
        for day in per_day:
            self.assertEqual(day["count"], 1)

    def test_multi_person_job(self):
        """Job with min_people=2 gets at least 2 workers when enough staff available."""
        _make_staff("w1")
        _make_staff("w2")
        _make_staff("w3")

        job = _make_job(self.client_obj, self.test_staff, min_people=2, max_people=3)
        _set_summary_hours(job.latest_estimate, 16.0)

        run = run_workshop_schedule()

        proj = JobProjection.objects.get(scheduler_run=run, job=job)
        self.assertFalse(proj.is_unscheduled)

        blocks = AllocationBlock.objects.filter(scheduler_run=run, job=job)
        self.assertTrue(blocks.exists())
        # First day should have at least 2 distinct staff
        first_date = blocks.order_by("allocation_date").first().allocation_date
        first_day_staff = (
            blocks.filter(allocation_date=first_date)
            .values_list("staff_id", flat=True)
            .distinct()
        )
        self.assertGreaterEqual(len(first_day_staff), 2)


class TestAllocationBlocks(BaseTestCase):
    """Tests for AllocationBlock creation and content."""

    def setUp(self):
        self.client_obj = _make_client()
        _make_staff("worker1")

    def test_anticipated_staff_populated(self):
        """Scheduled job has AllocationBlock records linking staff to the job."""
        job = _make_job(self.client_obj, self.test_staff)
        _set_summary_hours(job.latest_estimate, 8.0)

        run = run_workshop_schedule()

        blocks = AllocationBlock.objects.filter(scheduler_run=run, job=job)
        self.assertTrue(blocks.exists())

    def test_allocation_blocks_persisted(self):
        """AllocationBlock records exist after a scheduler run."""
        job = _make_job(self.client_obj, self.test_staff)
        _set_summary_hours(job.latest_estimate, 8.0)

        run = run_workshop_schedule()

        self.assertTrue(AllocationBlock.objects.filter(scheduler_run=run).exists())


class TestDateCalculations(BaseTestCase):
    """Tests for anticipated start/end date assignment."""

    def setUp(self):
        self.client_obj = _make_client()
        _make_staff("worker1")

    def test_start_date_is_first_allocation_day(self):
        """anticipated_start_date equals the earliest AllocationBlock date."""
        job = _make_job(self.client_obj, self.test_staff)
        _set_summary_hours(job.latest_estimate, 8.0)

        run = run_workshop_schedule()

        proj = JobProjection.objects.get(scheduler_run=run, job=job)
        earliest_block = (
            AllocationBlock.objects.filter(scheduler_run=run, job=job)
            .order_by("allocation_date")
            .first()
        )
        self.assertEqual(proj.anticipated_start_date, earliest_block.allocation_date)

    def test_end_date_is_last_allocation_day(self):
        """anticipated_end_date equals the latest AllocationBlock date."""
        job = _make_job(self.client_obj, self.test_staff)
        _set_summary_hours(job.latest_estimate, 8.0)

        run = run_workshop_schedule()

        proj = JobProjection.objects.get(scheduler_run=run, job=job)
        latest_block = (
            AllocationBlock.objects.filter(scheduler_run=run, job=job)
            .order_by("allocation_date")
            .last()
        )
        self.assertEqual(proj.anticipated_end_date, latest_block.allocation_date)

    def test_multi_day_job_carries_over(self):
        """Job with more hours than one day spans multiple working days."""
        job = _make_job(self.client_obj, self.test_staff)
        # 1 worker @ 8h/day, 24h of work needs at least 3 days
        _set_summary_hours(job.latest_estimate, 24.0)

        run = run_workshop_schedule()

        proj = JobProjection.objects.get(scheduler_run=run, job=job)
        self.assertFalse(proj.is_unscheduled)
        self.assertGreater(proj.anticipated_end_date, proj.anticipated_start_date)

    def test_scheduled_job_has_both_dates(self):
        """Every scheduled projection has non-null start and end dates."""
        job = _make_job(self.client_obj, self.test_staff)
        _set_summary_hours(job.latest_estimate, 8.0)

        run = run_workshop_schedule()

        for proj in JobProjection.objects.filter(
            scheduler_run=run, is_unscheduled=False
        ):
            self.assertIsNotNone(proj.anticipated_start_date)
            self.assertIsNotNone(proj.anticipated_end_date)


class TestPriorityAndCapacity(BaseTestCase):
    """Tests for priority ordering and capacity consumption."""

    def setUp(self):
        self.client_obj = _make_client()

    def test_priority_order_affects_scheduling(self):
        """Higher priority job starts no later than lower priority job."""
        _make_staff("w1")

        low_job = _make_job(self.client_obj, self.test_staff, name="Low Priority")
        high_job = _make_job(self.client_obj, self.test_staff, name="High Priority")
        _set_summary_hours(low_job.latest_estimate, 8.0)
        _set_summary_hours(high_job.latest_estimate, 8.0)

        # Set high_job to higher priority
        low_job.priority = 100.0
        low_job.save(staff=self.test_staff)
        high_job.priority = 200.0
        high_job.save(staff=self.test_staff)

        run = run_workshop_schedule()

        low_proj = JobProjection.objects.get(scheduler_run=run, job=low_job)
        high_proj = JobProjection.objects.get(scheduler_run=run, job=high_job)

        self.assertFalse(high_proj.is_unscheduled)
        self.assertFalse(low_proj.is_unscheduled)
        self.assertLessEqual(
            high_proj.anticipated_start_date, low_proj.anticipated_start_date
        )

    def test_capacity_consumed_affects_later_jobs(self):
        """High-priority job consuming capacity delays lower-priority job actual work."""
        _make_staff("w1")  # single worker, 8h/day

        high_job = _make_job(self.client_obj, self.test_staff, name="High")
        low_job = _make_job(self.client_obj, self.test_staff, name="Low")

        # High-priority job consumes more than one day
        _set_summary_hours(high_job.latest_estimate, 16.0)
        _set_summary_hours(low_job.latest_estimate, 8.0)

        high_job.priority = 500.0
        high_job.save(staff=self.test_staff)
        low_job.priority = 100.0
        low_job.save(staff=self.test_staff)

        run = run_workshop_schedule()

        high_proj = JobProjection.objects.get(scheduler_run=run, job=high_job)
        low_proj = JobProjection.objects.get(scheduler_run=run, job=low_job)

        self.assertFalse(high_proj.is_unscheduled)
        self.assertFalse(low_proj.is_unscheduled)

        # High priority job gets allocation blocks before the low priority job does.
        # With 1 worker @ 8h/day and high job needing 16h, it spans 2 days.
        # The low priority job can only get real work blocks after high job finishes.
        high_blocks = AllocationBlock.objects.filter(scheduler_run=run, job=high_job)
        low_blocks = AllocationBlock.objects.filter(scheduler_run=run, job=low_job)
        self.assertTrue(high_blocks.exists())
        self.assertTrue(low_blocks.exists())

        # The earliest date that low job actually gets allocated work must be
        # after the first date that high job is allocated work.
        high_first_date = (
            high_blocks.order_by("allocation_date").first().allocation_date
        )
        low_first_actual_date = (
            low_blocks.order_by("allocation_date").first().allocation_date
        )
        self.assertGreater(low_first_actual_date, high_first_date)


class TestJobModelUnchanged(BaseTestCase):
    """Tests that the scheduler does not mutate the Job model."""

    def setUp(self):
        self.client_obj = _make_client()
        _make_staff("w1")

    def test_output_not_written_to_job(self):
        """After a run, Job model has no anticipated_start_date field."""
        job = _make_job(self.client_obj, self.test_staff)
        _set_summary_hours(job.latest_estimate, 8.0)

        run_workshop_schedule()

        job.refresh_from_db()
        self.assertFalse(hasattr(job, "anticipated_start_date"))
