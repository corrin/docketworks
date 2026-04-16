import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Dict, List, Optional

from django.db import models, transaction
from django.utils import timezone

from apps.accounts.models import Staff
from apps.job.models import Job
from apps.operations.models import AllocationBlock, JobProjection, SchedulerRun
from apps.operations.models.job_projection import UnscheduledReason

logger = logging.getLogger(__name__)

SCHEDULE_HORIZON_DAYS = 180
ALGORITHM_VERSION = "v1"


@dataclass
class JobScheduleState:
    """Mutable state for a job being scheduled."""

    job: Job
    remaining_hours: float
    start_date: Optional[date] = None
    end_date: Optional[date] = None


@dataclass
class UnschedulableJob:
    job: Job
    remaining_hours: float
    reason: str


def _get_actual_hours(job: Job) -> float:
    """Sum quantity of all time CostLines in the latest actual CostSet."""
    if not job.latest_actual_id:
        return 0.0
    time_lines = job.latest_actual.cost_lines.filter(kind="time")
    total = sum(float(line.quantity) for line in time_lines)
    return total


def _compute_remaining_hours(
    job: Job,
) -> tuple[float, Optional[str]]:
    """
    Compute remaining hours for a job.

    Returns (remaining_hours, unscheduled_reason).
    If unscheduled_reason is not None the job cannot be scheduled.
    """
    actual_hours = _get_actual_hours(job)

    estimate_hours = 0.0
    if job.latest_estimate_id:
        estimate_hours = float(job.latest_estimate.summary.get("hours", 0.0))

    estimate_remaining = estimate_hours - actual_hours
    if estimate_remaining > 0:
        return estimate_remaining, None

    # Estimate exhausted or missing — fall back to quote
    quote_hours = 0.0
    if job.latest_quote_id:
        quote_hours = float(job.latest_quote.summary.get("hours", 0.0))

    quote_remaining = quote_hours - actual_hours
    if quote_remaining > 0:
        return quote_remaining, None

    return 0.0, UnscheduledReason.MISSING_ESTIMATE_OR_QUOTE_HOURS


def _gather_workshop_staff(today: date) -> List[Staff]:
    """Return all currently active workshop staff."""
    return list(
        Staff.objects.filter(is_workshop_staff=True).filter(
            models.Q(date_left__isnull=True) | models.Q(date_left__gt=today)
        )
    )


def _classify_jobs(
    jobs: List[Job],
    staff_count: int,
) -> tuple[List[JobScheduleState], List[UnschedulableJob]]:
    """
    Separate jobs into schedulable and unschedulable.
    Returns (schedulable_states, unschedulable_list).
    """
    schedulable: List[JobScheduleState] = []
    unschedulable: List[UnschedulableJob] = []

    for job in jobs:
        remaining_hours, hours_reason = _compute_remaining_hours(job)

        if hours_reason is not None:
            unschedulable.append(
                UnschedulableJob(
                    job=job,
                    remaining_hours=remaining_hours,
                    reason=hours_reason,
                )
            )
            continue

        if job.max_people < job.min_people:
            unschedulable.append(
                UnschedulableJob(
                    job=job,
                    remaining_hours=remaining_hours,
                    reason=UnscheduledReason.INVALID_STAFFING_CONSTRAINTS,
                )
            )
            continue

        if job.min_people > staff_count:
            unschedulable.append(
                UnschedulableJob(
                    job=job,
                    remaining_hours=remaining_hours,
                    reason=UnscheduledReason.MIN_PEOPLE_EXCEEDS_STAFF,
                )
            )
            continue

        schedulable.append(JobScheduleState(job=job, remaining_hours=remaining_hours))

    return schedulable, unschedulable


def _simulate(
    schedulable: List[JobScheduleState],
    all_staff: List[Staff],
    today: date,
) -> List[AllocationBlock]:
    """
    Day-by-day greedy scheduling simulation.

    Mutates each JobScheduleState (remaining_hours, start_date, end_date).
    Returns a list of unsaved AllocationBlock instances (without scheduler_run set).
    """
    blocks: List[AllocationBlock] = []
    sequence = 0

    active_jobs = list(schedulable)  # copy — we pop completed jobs out

    for day_offset in range(SCHEDULE_HORIZON_DAYS):
        if not active_jobs:
            break

        current_date = today + timedelta(days=day_offset)

        # Build per-staff remaining capacity for today
        staff_capacity: Dict[int, float] = {}
        for staff_member in all_staff:
            daily_hours = staff_member.get_scheduled_hours(current_date)
            if daily_hours > 0:
                staff_capacity[staff_member.pk] = daily_hours

        available_staff = [s for s in all_staff if s.pk in staff_capacity]

        if not available_staff:
            continue  # non-working day for all staff

        still_active: List[JobScheduleState] = []

        for state in active_jobs:
            job = state.job

            workers_to_assign = min(job.max_people, len(available_staff))
            if workers_to_assign < job.min_people:
                # Cannot staff this job today — skip but keep in queue
                still_active.append(state)
                continue

            # Pick the workers with most remaining capacity today
            eligible = sorted(
                available_staff,
                key=lambda s: staff_capacity[s.pk],
                reverse=True,
            )
            assigned = eligible[:workers_to_assign]

            if state.start_date is None:
                state.start_date = current_date

            hours_allocated_today = 0.0
            for worker in assigned:
                worker_capacity = staff_capacity[worker.pk]
                # Each worker takes an equal share but no more than their capacity
                share = state.remaining_hours / len(assigned)
                worker_hours = min(worker_capacity, share)

                if worker_hours <= 0:
                    continue

                blocks.append(
                    AllocationBlock(
                        job=job,
                        staff=worker,
                        allocation_date=current_date,
                        allocated_hours=worker_hours,
                        sequence=sequence,
                    )
                )
                sequence += 1

                staff_capacity[worker.pk] -= worker_hours
                hours_allocated_today += worker_hours

            state.remaining_hours -= hours_allocated_today
            state.end_date = current_date

            if state.remaining_hours <= 0:
                state.remaining_hours = 0.0
                # Do not add to still_active — job is complete
            else:
                still_active.append(state)

        active_jobs = still_active

    return blocks


@transaction.atomic
def _persist_results(
    schedulable: List[JobScheduleState],
    unschedulable: List[UnschedulableJob],
    blocks: List[AllocationBlock],
) -> SchedulerRun:
    """Create SchedulerRun, JobProjection, and AllocationBlock records."""
    timezone.now().date()

    total_jobs = len(schedulable) + len(unschedulable)
    scheduler_run = SchedulerRun.objects.create(
        algorithm_version=ALGORITHM_VERSION,
        succeeded=True,
        job_count=total_jobs,
        unscheduled_count=len(unschedulable),
    )

    projections: List[JobProjection] = []

    for state in schedulable:
        is_late = False
        if state.job.delivery_date and state.end_date:
            is_late = state.end_date > state.job.delivery_date

        projections.append(
            JobProjection(
                scheduler_run=scheduler_run,
                job=state.job,
                anticipated_start_date=state.start_date,
                anticipated_end_date=state.end_date,
                remaining_hours=state.remaining_hours,
                is_late=is_late,
                is_unscheduled=False,
            )
        )

    for item in unschedulable:
        projections.append(
            JobProjection(
                scheduler_run=scheduler_run,
                job=item.job,
                anticipated_start_date=None,
                anticipated_end_date=None,
                remaining_hours=item.remaining_hours,
                is_late=False,
                is_unscheduled=True,
                unscheduled_reason=item.reason,
            )
        )

    JobProjection.objects.bulk_create(projections)

    # Assign scheduler_run to all blocks before bulk-creating
    for block in blocks:
        block.scheduler_run = scheduler_run

    AllocationBlock.objects.bulk_create(blocks)

    return scheduler_run


def run_workshop_schedule() -> SchedulerRun:
    """
    Run the workshop scheduling simulation and persist results.

    Returns the SchedulerRun record.
    Raises on failure — caller must handle via persist_app_error.
    """
    today = timezone.now().date()

    jobs = list(
        Job.objects.filter(status__in=["approved", "in_progress"])
        .select_related("latest_estimate", "latest_quote", "latest_actual")
        .prefetch_related("latest_actual__cost_lines")
    )

    all_staff = _gather_workshop_staff(today)

    schedulable, unschedulable = _classify_jobs(jobs, len(all_staff))

    # Sort schedulable jobs descending by priority
    schedulable.sort(key=lambda s: s.job.priority, reverse=True)

    blocks = _simulate(schedulable, all_staff, today)

    scheduler_run = _persist_results(schedulable, unschedulable, blocks)

    logger.info(
        "Workshop schedule run complete: %d jobs scheduled, %d unschedulable, "
        "%d allocation blocks created",
        len(schedulable),
        len(unschedulable),
        len(blocks),
    )

    return scheduler_run
