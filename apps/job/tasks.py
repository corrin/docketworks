"""Celery tasks for the job app.

Beat-scheduled paid-flag and auto-archive jobs. Per ADR 0024: tasks are
idempotent; failures persist via AppError (ADR 0019).
"""

import logging
import os

from celery import shared_task
from django.conf import settings
from django.db import close_old_connections

from apps.job.services.file_service import create_thumbnail, get_thumbnail_folder
from apps.workflow.exceptions import AlreadyLoggedException
from apps.workflow.services.error_persistence import persist_and_raise

logger = logging.getLogger("apps.job.tasks")


@shared_task(name="apps.job.tasks.create_job_file_thumbnail_task")
def create_job_file_thumbnail_task(job_file_id: str) -> None:
    """Create a thumbnail for a job file after the upload response returns."""
    logger.info("Creating thumbnail for job file %s.", job_file_id)
    try:
        close_old_connections()
        from apps.job.models import JobFile

        job_file = JobFile.objects.select_related("job").get(id=job_file_id)
        if job_file.status != "active":
            logger.info("Skipping thumbnail for inactive job file %s.", job_file_id)
            return

        if not job_file.mime_type.startswith("image/"):
            logger.info("Skipping thumbnail for non-image job file %s.", job_file_id)
            return

        source_path = os.path.join(settings.DROPBOX_WORKFLOW_FOLDER, job_file.file_path)
        if not os.path.exists(source_path):
            raise FileNotFoundError(f"Job file does not exist: {source_path}")

        thumb_folder = get_thumbnail_folder(job_file.job.job_number)
        thumb_path = os.path.join(thumb_folder, f"{job_file.filename}.thumb.jpg")
        if os.path.exists(thumb_path):
            logger.info("Thumbnail already exists for job file %s.", job_file_id)
            return

        create_thumbnail(source_path, thumb_path)
        logger.info("Created thumbnail for job file %s.", job_file_id)
    except AlreadyLoggedException:
        raise
    except Exception as exc:
        logger.error(
            "Error creating thumbnail for job file %s: %s",
            job_file_id,
            exc,
            exc_info=True,
        )
        persist_and_raise(exc, additional_context={"job_file_id": job_file_id})


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
