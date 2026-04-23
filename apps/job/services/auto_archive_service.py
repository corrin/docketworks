"""Service for auto-archiving recently completed jobs that are paid or rejected."""

import logging
from dataclasses import dataclass, field
from datetime import timedelta
from typing import List

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Staff
from apps.job.models import Job

logger = logging.getLogger(__name__)


@dataclass
class AutoArchiveResult:
    """Result of auto-archive operation."""

    jobs_archived: int
    duration_seconds: float
    archived_jobs: List[Job] = field(default_factory=list)


class AutoArchiveService:
    """Service for auto-archiving recently completed jobs that are paid or rejected."""

    @staticmethod
    def auto_archive_completed_jobs(
        dry_run: bool = False, verbose: bool = False
    ) -> AutoArchiveResult:
        """
        Archive recently_completed jobs that have been in that status for 6+ days
        and are either paid or rejected.

        Args:
            dry_run: If True, don't make any changes
            verbose: If True, log detailed information

        Returns:
            AutoArchiveResult with operation details
        """
        start_time = timezone.now()
        threshold = timezone.now() - timedelta(days=6)

        base_filter = dict(status="recently_completed", completed_at__lte=threshold)

        paid_jobs = list(Job.objects.filter(**base_filter, paid=True))
        rejected_jobs = list(Job.objects.filter(**base_filter, rejected_flag=True))

        # Combine and deduplicate (a job could be both paid and rejected)
        seen_ids = set()
        eligible_jobs = []
        for job in paid_jobs + rejected_jobs:
            if job.pk not in seen_ids:
                seen_ids.add(job.pk)
                eligible_jobs.append(job)

        if verbose:
            logger.info(
                f"Found {len(eligible_jobs)} recently completed jobs "
                f"(paid or rejected) older than 6 days"
            )

        archived_jobs = []

        for job in eligible_jobs:
            if verbose:
                logger.info(
                    f"Job {job.job_number} - {job.name}: "
                    f"completed_at={job.completed_at}, paid={job.paid}, "
                    f"rejected={job.rejected_flag}"
                )
            if dry_run:
                logger.info(f"Would archive job {job.job_number} - {job.name}")
            archived_jobs.append(job)

        if not dry_run and archived_jobs:
            automation_user = Staff.get_automation_user()
            with transaction.atomic():
                for job in archived_jobs:
                    job.status = "archived"
                    job.save(staff=automation_user)
                    logger.info(f"Job {job.job_number} ({job.name}) auto-archived")

        end_time = timezone.now()
        duration = (end_time - start_time).total_seconds()

        return AutoArchiveResult(
            jobs_archived=len(archived_jobs),
            duration_seconds=duration,
            archived_jobs=archived_jobs,
        )
