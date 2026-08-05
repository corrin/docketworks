"""Celery tasks for the job application.

Task names are part of the operational contract because Beat entries reference
them. Per ADR 0024, tasks are idempotent;
failures persist via AppError (ADR 0019).

Beat wiring lives in config/celery.py: ``set_paid_flag_task`` daily 02:00 NZT
and ``auto_archive_completed_jobs_task`` daily 03:00 NZT.

``celery-types`` provides the ``shared_task`` and ``apply_async`` typing
directly.
"""

import logging
from pathlib import Path

from celery import shared_task
from django.conf import settings
from django.core.cache import caches
from django.db import close_old_connections, connection, transaction

from apps.core.errors import AppErrorContext, persist_app_error

logger = logging.getLogger("apps.job.tasks")

JOB_SUMMARY_PDF_REFRESH_QUEUED_KEY = "job-summary-pdf-refresh-queued"
JOB_SUMMARY_PDF_REFRESH_RUNNING_KEY = "job-summary-pdf-refresh-running"
JOB_SUMMARY_PDF_REFRESH_LOCK_SECONDS = 15 * 60
JOB_SUMMARY_PDF_REFRESH_QUEUED_SECONDS = 15 * 60
JOB_SUMMARY_PDF_REFRESH_DELAY_SECONDS = 30
JOB_SUMMARY_PDF_REFRESH_BATCH_SIZE = 20


def request_job_summary_pdf_refresh() -> None:
    """Request one bounded JobSummary.pdf refresh after commit."""
    transaction.on_commit(_queue_job_summary_pdf_refresh)


def _schedule_job_summary_pdf_refresh(countdown: int) -> None:
    refresh_job_summary_pdfs_task.apply_async(
        kwargs={"limit": JOB_SUMMARY_PDF_REFRESH_BATCH_SIZE},
        countdown=countdown,
    )


def _queue_job_summary_pdf_refresh(countdown: int | None = None) -> None:
    cache = caches["shared"]
    queued = cache.add(
        JOB_SUMMARY_PDF_REFRESH_QUEUED_KEY,
        True,
        timeout=JOB_SUMMARY_PDF_REFRESH_QUEUED_SECONDS,
    )
    if not queued:
        logger.debug("JobSummary.pdf refresh is already queued.")
        return

    scheduled_countdown = JOB_SUMMARY_PDF_REFRESH_DELAY_SECONDS if countdown is None else countdown
    try:
        _schedule_job_summary_pdf_refresh(scheduled_countdown)
    except Exception as exc:
        cache.delete(JOB_SUMMARY_PDF_REFRESH_QUEUED_KEY)
        logger.exception("Error queueing JobSummary.pdf refresh.")
        persist_app_error(
            exc,
            AppErrorContext(
                additional_context={
                    "countdown": scheduled_countdown,
                    "limit": JOB_SUMMARY_PDF_REFRESH_BATCH_SIZE,
                }
            ),
        )
        raise


@shared_task(name="apps.job.tasks.create_job_file_thumbnail_task")
def create_job_file_thumbnail_task(job_file_id: str) -> None:
    """Create a thumbnail for a job file after the upload response returns."""
    logger.info("Creating thumbnail for job file %s.", job_file_id)
    try:
        # Eager mode runs inside the request's transaction; closing the
        # connection there would kill it (same guard as the refresh task).
        if not connection.in_atomic_block:
            close_old_connections()
        # Service imports stay function-local so the worker only pays for them
        # when the task actually runs.
        from apps.job.models import JobFile  # noqa: PLC0415
        from apps.job.services.file_service import (  # noqa: PLC0415
            create_thumbnail,
            get_thumbnail_folder,
        )

        job_file = JobFile.objects.select_related("job").get(id=job_file_id)
        if job_file.status != "active":
            logger.info("Skipping thumbnail for inactive job file %s.", job_file_id)
            return

        if not (job_file.mime_type or "").startswith("image/"):
            logger.info("Skipping thumbnail for non-image job file %s.", job_file_id)
            return

        source_path = Path(settings.DROPBOX_WORKFLOW_FOLDER) / job_file.file_path
        if not source_path.exists():
            raise FileNotFoundError(f"Job file does not exist: {source_path}")

        thumb_folder = get_thumbnail_folder(job_file.job.job_number)
        safe_filename = Path(job_file.filename).name
        thumb_path = Path(thumb_folder) / f"{safe_filename}.thumb.jpg"
        if thumb_path.exists():
            logger.info("Thumbnail already exists for job file %s.", job_file_id)
            return

        create_thumbnail(str(source_path), str(thumb_path))
        logger.info("Created thumbnail for job file %s.", job_file_id)
    except Exception as exc:
        logger.exception("Error creating thumbnail for job file %s.", job_file_id)
        persist_app_error(exc, AppErrorContext(additional_context={"job_file_id": job_file_id}))
        raise


@shared_task(name="apps.job.tasks.refresh_job_summary_pdfs_task")
def refresh_job_summary_pdfs_task(limit: int = JOB_SUMMARY_PDF_REFRESH_BATCH_SIZE) -> None:
    """Refresh a bounded batch of missing/stale disaster-recovery PDFs.

    When a batch leaves work behind (or a new refresh request arrived while
    running), a follow-up run is chained immediately so large backlogs drain
    batch by batch.
    """
    logger.info("Refreshing stale JobSummary.pdf files.")
    cache = caches["shared"]
    if not cache.add(
        JOB_SUMMARY_PDF_REFRESH_RUNNING_KEY,
        True,
        timeout=JOB_SUMMARY_PDF_REFRESH_LOCK_SECONDS,
    ):
        logger.info("Skipping JobSummary.pdf refresh; another run is active.")
        return

    follow_up_required = False
    try:
        if not connection.in_atomic_block:
            close_old_connections()
        from apps.job.services.job_summary_pdf_service import JobSummaryPdfService  # noqa: PLC0415

        cache.delete(JOB_SUMMARY_PDF_REFRESH_QUEUED_KEY)
        refreshed, remaining = JobSummaryPdfService.refresh_stale(limit)
        logger.info("Refreshed %s stale JobSummary.pdf files.", refreshed)
        follow_up_required = remaining or bool(cache.get(JOB_SUMMARY_PDF_REFRESH_QUEUED_KEY))
    except Exception as exc:
        cache.delete(JOB_SUMMARY_PDF_REFRESH_QUEUED_KEY)
        logger.exception("Error refreshing JobSummary.pdf files.")
        persist_app_error(exc, AppErrorContext(additional_context={"limit": limit}))
        raise
    finally:
        cache.delete(JOB_SUMMARY_PDF_REFRESH_RUNNING_KEY)

    if follow_up_required:
        cache.delete(JOB_SUMMARY_PDF_REFRESH_QUEUED_KEY)
        _queue_job_summary_pdf_refresh(countdown=0)


@shared_task(name="apps.job.tasks.set_paid_flag_task")
def set_paid_flag_task() -> None:
    """Mark completed jobs with fully paid invoices as 'paid'.

    Beat-scheduled daily 02:00 NZT. Runs before auto_archive_completed_jobs
    so freshly marked jobs become eligible for archival.
    """
    logger.info("Running set_paid_flag_task.")
    try:
        if not connection.in_atomic_block:
            close_old_connections()
        from apps.job.services.paid_flag_service import update_paid_flags  # noqa: PLC0415

        result = update_paid_flags(dry_run=False, verbose=True)
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
    except Exception as exc:
        logger.exception("Error during set_paid_flag_task.")
        persist_app_error(exc)
        raise


@shared_task(name="apps.job.tasks.auto_archive_completed_jobs_task")
def auto_archive_completed_jobs_task() -> None:
    """Auto-archive recently completed, paid jobs that are 6+ days old.

    Beat-scheduled daily 03:00 NZT (one hour after set_paid_flag_task).
    """
    logger.info("Running auto_archive_completed_jobs_task.")
    try:
        if not connection.in_atomic_block:
            close_old_connections()
        from apps.job.services.auto_archive_service import (  # noqa: PLC0415
            auto_archive_completed_jobs,
        )

        result = auto_archive_completed_jobs(dry_run=False, verbose=True)
        logger.info(
            "Auto-archived %s jobs. Operation completed in %.2f seconds.",
            result.jobs_archived,
            result.duration_seconds,
        )
    except Exception as exc:
        logger.exception("Error during auto_archive_completed_jobs_task.")
        persist_app_error(exc)
        raise
