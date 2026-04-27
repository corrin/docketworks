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
        """Job with estimate hours schedules; remaining = estimate - actual at run time."""
        job = _make_job(self.client_obj, self.test_staff)
        _set_summary_hours(job.latest_estimate, 10.0)

        run = run_workshop_schedule()

        proj = JobProjection.objects.get(scheduler_run=run, job=job)
        self.assertFalse(proj.is_unscheduled)
        # remaining_hours is the at-run-time value (10h estimate, no actual),
        # not the post-simulation residual.
        self.assertAlmostEqual(proj.remaining_hours, 10.0, delta=0.1)

    def test_quote_fallback_when_estimate_zero(self):
        """Job with zero estimate but valid quote schedules using quote hours."""
        job = _make_job(self.client_obj, self.test_staff)
        _set_summary_hours(job.latest_estimate, 0.0)
        _set_summary_hours(job.latest_quote, 8.0)

        run = run_workshop_schedule()

        proj = JobProjection.objects.get(scheduler_run=run, job=job)
        self.assertFalse(proj.is_unscheduled)
        self.assertAlmostEqual(proj.remaining_hours, 8.0, delta=0.1)

    def test_remaining_hours_is_at_run_time_not_post_simulation(self):
        """Multi-day jobs persist the at-run-time remaining hours, not the
        post-simulation residual. The frontend needs to display 'X hours of work
        left' — once the simulation has consumed the work, that value is 0,
        which would defeat the contract."""
        job = _make_job(self.client_obj, self.test_staff)
        # 24h of work for one worker @ 8h/day spans three days.
        _set_summary_hours(job.latest_estimate, 24.0)

        run = run_workshop_schedule()

        proj = JobProjection.objects.get(scheduler_run=run, job=job)
        self.assertFalse(proj.is_unscheduled)
        self.assertAlmostEqual(proj.remaining_hours, 24.0, delta=0.1)

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


class TestAssignedStaffPreference(BaseTestCase):
    """Tests that explicitly-assigned staff are preferred when available."""

    def setUp(self):
        self.client_obj = _make_client()

    def test_assigned_available_staff_chosen_over_others(self):
        """When a job has assigned staff and they're available, they get the work."""
        # Three workers — without assignment, the scheduler picks by capacity
        # which would tie and fall back to insertion order.
        w1 = _make_staff("w1")
        _make_staff("w2")
        _make_staff("w3")

        job = _make_job(self.client_obj, self.test_staff, min_people=1, max_people=1)
        _set_summary_hours(job.latest_estimate, 8.0)
        job.people.add(w1)

        run = run_workshop_schedule()

        blocks = AllocationBlock.objects.filter(scheduler_run=run, job=job)
        self.assertTrue(blocks.exists())
        staff_ids = set(blocks.values_list("staff_id", flat=True))
        self.assertEqual(staff_ids, {w1.id})

    def test_assigned_staff_preferred_even_with_lower_capacity(self):
        """Assigned worker is picked over a non-assigned worker with more
        remaining capacity (capacity sort would otherwise win)."""
        # Big-capacity worker is unassigned; small-capacity worker is assigned.
        big = _make_staff("big", hours=8.0)
        small = _make_staff("small", hours=4.0)

        job = _make_job(self.client_obj, self.test_staff, min_people=1, max_people=1)
        _set_summary_hours(job.latest_estimate, 4.0)
        job.people.add(small)

        run = run_workshop_schedule()

        blocks = AllocationBlock.objects.filter(scheduler_run=run, job=job)
        self.assertTrue(blocks.exists())
        staff_ids = set(blocks.values_list("staff_id", flat=True))
        self.assertIn(small.id, staff_ids)
        self.assertNotIn(big.id, staff_ids)

    def test_remaining_slots_filled_from_unassigned_pool(self):
        """If max_people exceeds the number of assigned staff, remaining slots
        are filled from the unassigned pool."""
        w1 = _make_staff("w1")
        w2 = _make_staff("w2")
        w3 = _make_staff("w3")

        job = _make_job(self.client_obj, self.test_staff, min_people=2, max_people=2)
        _set_summary_hours(job.latest_estimate, 16.0)
        # Only one person assigned but the job needs two
        job.people.add(w1)

        run = run_workshop_schedule()

        blocks = AllocationBlock.objects.filter(scheduler_run=run, job=job)
        self.assertTrue(blocks.exists())
        first_date = blocks.order_by("allocation_date").first().allocation_date
        first_day_staff = set(
            blocks.filter(allocation_date=first_date).values_list("staff_id", flat=True)
        )
        self.assertIn(w1.id, first_day_staff)
        # Second slot must be one of the others
        self.assertTrue({w2.id, w3.id} & first_day_staff)

    def test_unavailable_assigned_staff_falls_back_to_others(self):
        """If the assigned worker has no capacity today, the scheduler still
        picks an available worker rather than skipping the job."""
        # Assigned worker doesn't work any day (no scheduled hours)
        unavailable = Staff.objects.create_user(
            email="staff-unavailable@test.example",
            password="testpass",
            first_name="Unavailable",
            last_name="Worker",
            is_workshop_staff=True,
            hours_mon=Decimal("0"),
            hours_tue=Decimal("0"),
            hours_wed=Decimal("0"),
            hours_thu=Decimal("0"),
            hours_fri=Decimal("0"),
            hours_sat=Decimal("0"),
            hours_sun=Decimal("0"),
        )
        backup = _make_staff("backup")

        job = _make_job(self.client_obj, self.test_staff, min_people=1, max_people=1)
        _set_summary_hours(job.latest_estimate, 8.0)
        job.people.add(unavailable)

        run = run_workshop_schedule()

        blocks = AllocationBlock.objects.filter(scheduler_run=run, job=job)
        self.assertTrue(blocks.exists())
        staff_ids = set(blocks.values_list("staff_id", flat=True))
        self.assertEqual(staff_ids, {backup.id})


class TestBookedTimeReducesCapacity(BaseTestCase):
    """Tests that pre-existing time CostLines (worked time, leave) reduce a
    staff member's available capacity for the day."""

    def setUp(self):
        from apps.workflow.models.company_defaults import CompanyDefaults

        self.client_obj = _make_client()
        # Disable the efficiency factor so this class can assert on raw
        # clock-hour math. The factor itself is covered by TestEfficiencyFactor.
        cd = CompanyDefaults.get_solo()
        cd.workshop_efficiency_factor = Decimal("1.000")
        cd.save()

    def _make_special_leave_job(self):
        """Create a leave-style job with an actual CostSet for booking time
        against (matches how create_leave_entries.py models leave)."""
        leave_job = Job(
            client=self.client_obj,
            name="Annual Leave",
            status="special",
            min_people=1,
            max_people=1,
        )
        leave_job.save(staff=self.test_staff)
        return leave_job

    def _book_time(self, staff, on_date, hours, cost_set):
        from apps.workflow.models import XeroPayItem

        pay_item = XeroPayItem.objects.get(name="Ordinary Time")
        CostLine.objects.create(
            cost_set=cost_set,
            kind="time",
            desc=f"booking - {staff.email}",
            quantity=Decimal(str(hours)),
            unit_cost=Decimal("0.00"),
            unit_rev=Decimal("0.00"),
            accounting_date=on_date,
            xero_pay_item=pay_item,
            meta={
                "staff_id": str(staff.id),
                "date": on_date.isoformat(),
                "is_billable": False,
                "wage_rate_multiplier": 1.0,
            },
        )

    def test_full_day_leave_blocks_allocation(self):
        """A full-day leave entry on day D removes that worker from day D."""
        on_leave = _make_staff("on_leave")
        backup = _make_staff("backup")

        leave_job = self._make_special_leave_job()
        # Book 8h leave for `on_leave` on every working day this week so the
        # simulator can never pick a day that's free.
        from datetime import timedelta as _td

        today = date.today()
        for offset in range(7):
            d = today + _td(days=offset)
            if d.weekday() < 5:
                self._book_time(on_leave, d, 8.0, leave_job.latest_actual)

        job = _make_job(self.client_obj, self.test_staff, min_people=1, max_people=1)
        _set_summary_hours(job.latest_estimate, 8.0)

        run = run_workshop_schedule()

        blocks = AllocationBlock.objects.filter(scheduler_run=run, job=job)
        self.assertTrue(blocks.exists())
        staff_ids = set(blocks.values_list("staff_id", flat=True))
        self.assertNotIn(on_leave.id, staff_ids)
        self.assertIn(backup.id, staff_ids)

    def test_partial_day_booking_reduces_capacity(self):
        """Pre-booking 4h leaves only the remaining 4h available that day."""
        worker = _make_staff("part")
        leave_job = self._make_special_leave_job()
        today = date.today()
        # If today is a weekend, the test-staff weekday hours are 0 anyway —
        # advance to next weekday to keep the assertion meaningful.
        while today.weekday() >= 5:
            from datetime import timedelta as _td

            today = today + _td(days=1)
        self._book_time(worker, today, 4.0, leave_job.latest_actual)

        job = _make_job(self.client_obj, self.test_staff, min_people=1, max_people=1)
        # 12h of work — with 4h capacity today + 8h tomorrow it still fits in
        # two days (day 1 contributes only 4h, not 8h).
        _set_summary_hours(job.latest_estimate, 12.0)

        run = run_workshop_schedule()

        first_day_total = sum(
            float(b.allocated_hours)
            for b in AllocationBlock.objects.filter(
                scheduler_run=run, job=job, staff=worker, allocation_date=today
            )
        )
        # Capacity reduced from 8h to 4h
        self.assertAlmostEqual(first_day_total, 4.0, delta=0.01)

    def test_estimate_or_quote_costlines_do_not_reduce_capacity(self):
        """CostLines on estimate/quote CostSets are hypothetical and must not
        reduce real capacity."""
        worker = _make_staff("solo")

        # Put a fake "time" line on the worker's estimate cost set for an
        # unrelated job — this should NOT block them.
        unrelated = _make_job(
            self.client_obj,
            self.test_staff,
            name="Unrelated",
            min_people=1,
            max_people=1,
        )
        from apps.workflow.models import XeroPayItem

        pay_item = XeroPayItem.objects.get(name="Ordinary Time")
        today = date.today()
        while today.weekday() >= 5:
            from datetime import timedelta as _td

            today = today + _td(days=1)
        CostLine.objects.create(
            cost_set=unrelated.latest_estimate,  # estimate, not actual
            kind="time",
            desc="hypothetical",
            quantity=Decimal("8.000"),
            unit_cost=Decimal("0.00"),
            unit_rev=Decimal("0.00"),
            accounting_date=today,
            xero_pay_item=pay_item,
            meta={"staff_id": str(worker.id), "date": today.isoformat()},
        )

        job = _make_job(self.client_obj, self.test_staff, min_people=1, max_people=1)
        _set_summary_hours(job.latest_estimate, 8.0)

        run = run_workshop_schedule()

        blocks = AllocationBlock.objects.filter(
            scheduler_run=run, job=job, staff=worker, allocation_date=today
        )
        # Worker still has full capacity — gets the 8h day-one allocation
        total = sum(float(b.allocated_hours) for b in blocks)
        self.assertAlmostEqual(total, 8.0, delta=0.01)


class TestStartDateOnlyOnRealWork(BaseTestCase):
    """Regression: a job's start_date must reflect when work is actually
    allocated, not the first day the simulator considered it. With the bug,
    low-priority jobs whose chosen workers had drained capacity got
    start_date=today + zero AllocationBlocks."""

    def setUp(self):
        from apps.workflow.models.company_defaults import CompanyDefaults

        self.client_obj = _make_client()
        cd = CompanyDefaults.get_solo()
        cd.workshop_efficiency_factor = Decimal("1.000")
        cd.save()

    def test_low_priority_job_does_not_start_on_capacity_starved_day(self):
        """One worker, two jobs needing one person each. High-priority job
        consumes the day's capacity. Low-priority job must NOT have its
        start_date set to the same day — it can't have started yet."""
        _make_staff("solo")

        high = _make_job(self.client_obj, self.test_staff, name="High")
        low = _make_job(self.client_obj, self.test_staff, name="Low")
        # High priority needs all 8h today.
        _set_summary_hours(high.latest_estimate, 8.0)
        _set_summary_hours(low.latest_estimate, 8.0)

        high.priority = 500.0
        high.save(staff=self.test_staff)
        low.priority = 100.0
        low.save(staff=self.test_staff)

        run = run_workshop_schedule()

        high_proj = JobProjection.objects.get(scheduler_run=run, job=high)
        low_proj = JobProjection.objects.get(scheduler_run=run, job=low)

        # High runs today, low must run on a later day.
        self.assertGreater(
            low_proj.anticipated_start_date, high_proj.anticipated_start_date
        )

        # And there must be at least one AllocationBlock on the low job's
        # start_date, otherwise the start_date is a phantom.
        first_blocks = AllocationBlock.objects.filter(
            scheduler_run=run, job=low, allocation_date=low_proj.anticipated_start_date
        )
        self.assertTrue(first_blocks.exists())

    def test_unreachable_job_marked_unscheduled(self):
        """A schedulable job whose simulation never lands any work in the
        horizon is recorded as unscheduled with NOT_REACHED_IN_HORIZON."""
        # One worker, one always-busy high-priority job that never finishes,
        # plus a low-priority one that won't get a turn.
        _make_staff("solo")

        big = _make_job(self.client_obj, self.test_staff, name="Big")
        # Big enough to fill 180 days × 8h = 1440h; we only need to outlast
        # the horizon to starve `low` indefinitely.
        _set_summary_hours(big.latest_estimate, 5000.0)

        low = _make_job(self.client_obj, self.test_staff, name="Low")
        _set_summary_hours(low.latest_estimate, 8.0)

        big.priority = 1000.0
        big.save(staff=self.test_staff)
        low.priority = 1.0
        low.save(staff=self.test_staff)

        run = run_workshop_schedule()

        low_proj = JobProjection.objects.get(scheduler_run=run, job=low)
        self.assertTrue(low_proj.is_unscheduled)
        self.assertEqual(
            low_proj.unscheduled_reason,
            UnscheduledReason.NOT_REACHED_IN_HORIZON,
        )
        self.assertIsNone(low_proj.anticipated_start_date)
        self.assertIsNone(low_proj.anticipated_end_date)


class TestEfficiencyFactor(BaseTestCase):
    """Tests that CompanyDefaults.workshop_efficiency_factor scales daily
    schedulable capacity."""

    def setUp(self):
        self.client_obj = _make_client()

    def _set_efficiency(self, value):
        from apps.workflow.models.company_defaults import CompanyDefaults

        cd = CompanyDefaults.get_solo()
        cd.workshop_efficiency_factor = Decimal(str(value))
        cd.save()

    def test_factor_scales_daily_allocation(self):
        """At 0.75, an 8h-shift worker delivers 6h on day one of an 8h job."""
        worker = _make_staff("w")
        self._set_efficiency("0.750")

        job = _make_job(self.client_obj, self.test_staff, min_people=1, max_people=1)
        _set_summary_hours(job.latest_estimate, 8.0)

        run = run_workshop_schedule()

        first_date = (
            AllocationBlock.objects.filter(scheduler_run=run, job=job)
            .order_by("allocation_date")
            .first()
            .allocation_date
        )
        first_day_total = sum(
            float(b.allocated_hours)
            for b in AllocationBlock.objects.filter(
                scheduler_run=run, job=job, staff=worker, allocation_date=first_date
            )
        )
        self.assertAlmostEqual(first_day_total, 6.0, delta=0.01)

    def test_factor_one_means_full_capacity(self):
        """Setting efficiency to 1.0 restores nominal clock-hour capacity."""
        worker = _make_staff("w")
        self._set_efficiency("1.000")

        job = _make_job(self.client_obj, self.test_staff, min_people=1, max_people=1)
        _set_summary_hours(job.latest_estimate, 8.0)

        run = run_workshop_schedule()

        first_date = (
            AllocationBlock.objects.filter(scheduler_run=run, job=job)
            .order_by("allocation_date")
            .first()
            .allocation_date
        )
        first_day_total = sum(
            float(b.allocated_hours)
            for b in AllocationBlock.objects.filter(
                scheduler_run=run, job=job, staff=worker, allocation_date=first_date
            )
        )
        self.assertAlmostEqual(first_day_total, 8.0, delta=0.01)


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

    def test_today_uses_local_timezone_not_utc(self):
        """The scheduler must anchor 'today' on the project's local timezone
        (Pacific/Auckland). Using timezone.now().date() returns the UTC date,
        so for half the day in NZ the schedule shows yesterday as today."""
        from django.utils import timezone

        job = _make_job(self.client_obj, self.test_staff)
        _set_summary_hours(job.latest_estimate, 1.0)

        run_workshop_schedule()

        earliest_block = (
            AllocationBlock.objects.filter(job=job).order_by("allocation_date").first()
        )
        self.assertIsNotNone(earliest_block)
        self.assertGreaterEqual(earliest_block.allocation_date, timezone.localdate())

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
