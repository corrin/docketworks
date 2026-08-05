"""Auto-archive of settled completed jobs.

Archives ``recently_completed`` jobs 6+ days old that are paid or rejected.
Beat-scheduled daily via ``apps.job.tasks.auto_archive_completed_jobs_task``.
"""

import logging
from dataclasses import dataclass, field
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Staff
from apps.job.models import Job

logger = logging.getLogger(__name__)

AUTO_ARCHIVE_AGE_DAYS = 6


@dataclass
class AutoArchiveResult:
    """Result of an auto-archive operation."""

    jobs_archived: int
    duration_seconds: float
    archived_jobs: list[Job] = field(default_factory=list)


def auto_archive_completed_jobs(
    *, dry_run: bool = False, verbose: bool = False
) -> AutoArchiveResult:
    """Archive recently_completed jobs that settled 6+ days ago (paid or rejected).

    ``dry_run`` reports without changing anything; ``verbose`` logs per-job
    detail. Returns an AutoArchiveResult with operation details.
    """
    start_time = timezone.now()
    threshold = timezone.now() - timedelta(days=AUTO_ARCHIVE_AGE_DAYS)

    base_filter = {"status": "recently_completed", "completed_at__lte": threshold}

    paid_jobs = list(Job.objects.filter(**base_filter, paid=True))
    rejected_jobs = list(Job.objects.filter(**base_filter, rejected_flag=True))

    # Combine and deduplicate (a job could be both paid and rejected)
    seen_ids = set()
    eligible_jobs: list[Job] = []
    for job in paid_jobs + rejected_jobs:
        if job.pk not in seen_ids:
            seen_ids.add(job.pk)
            eligible_jobs.append(job)

    if verbose:
        logger.info(
            "Found %s recently completed jobs (paid or rejected) older than 6 days",
            len(eligible_jobs),
        )

    archived_jobs: list[Job] = []

    for job in eligible_jobs:
        if verbose:
            logger.info(
                "Job %s - %s: completed_at=%s, paid=%s, rejected=%s",
                job.job_number,
                job.name,
                job.completed_at,
                job.paid,
                job.rejected_flag,
            )
        if dry_run:
            logger.info("Would archive job %s - %s", job.job_number, job.name)
        archived_jobs.append(job)

    if not dry_run and archived_jobs:
        automation_user = Staff.get_automation_user()
        with transaction.atomic():
            for job in archived_jobs:
                job.status = "archived"
                job.save(staff=automation_user)
                logger.info("Job %s (%s) auto-archived", job.job_number, job.name)

    duration = (timezone.now() - start_time).total_seconds()

    return AutoArchiveResult(
        jobs_archived=len(archived_jobs),
        duration_seconds=duration,
        archived_jobs=archived_jobs,
    )
