"""Celery tasks for the job app.

Beat-scheduled paid-flag and auto-archive jobs. Per ADR 0024: tasks are
idempotent; failures persist via AppError (ADR 0019).
"""

import logging

from celery import shared_task
from django.db import close_old_connections

from apps.workflow.exceptions import AlreadyLoggedException
from apps.workflow.services.error_persistence import persist_and_raise

logger = logging.getLogger("apps.job.tasks")


@shared_task(name="apps.job.tasks.set_paid_flag_task")
def set_paid_flag_task() -> None:
    """Mark completed jobs with fully paid invoices as 'paid'.

    Beat-scheduled daily 02:00 NZT. Runs before auto_archive_completed_jobs
    so freshly marked jobs become eligible for archival.
    """
    logger.info("Running set_paid_flag_task.")
    try:
        close_old_connections()
        from apps.job.services.paid_flag_service import PaidFlagService

        result = PaidFlagService.update_paid_flags(dry_run=False, verbose=True)
        logger.info(
            "Successfully updated %s jobs as paid. "
            "Jobs with unpaid invoices: %s. "
            "Jobs without invoices: %s. "
            "Operation completed in %.2f seconds.",
            result.jobs_updated,
            result.unpaid_invoices,
            result.missing_invoices,
            result.duration_seconds,
        )
    except AlreadyLoggedException:
        raise
    except Exception as exc:
        logger.error("Error during set_paid_flag_task: %s", exc, exc_info=True)
        persist_and_raise(exc)


@shared_task(name="apps.job.tasks.auto_archive_completed_jobs_task")
def auto_archive_completed_jobs_task() -> None:
    """Auto-archive recently completed, paid jobs that are 6+ days old.

    Beat-scheduled daily 03:00 NZT (one hour after set_paid_flag_task).
    """
    logger.info("Running auto_archive_completed_jobs_task.")
    try:
        close_old_connections()
        from apps.job.services.auto_archive_service import AutoArchiveService

        result = AutoArchiveService.auto_archive_completed_jobs(
            dry_run=False, verbose=True
        )
        logger.info(
            "Auto-archived %s jobs. Operation completed in %.2f seconds.",
            result.jobs_archived,
            result.duration_seconds,
        )
    except AlreadyLoggedException:
        raise
    except Exception as exc:
        logger.error(
            "Error during auto_archive_completed_jobs_task: %s", exc, exc_info=True
        )
        persist_and_raise(exc)
