"""Celery tasks for the job app, ported from v1 ``apps/job/tasks.py``.

Task names are part of the operational contract (beat schedule entries
reference them) and stay identical to v1. Per ADR 0024: tasks are idempotent;
failures persist via AppError (ADR 0019).

Beat wiring (config/celery.py, not here): v1 scheduled ``set_paid_flag_task``
daily 02:00 NZT and ``auto_archive_completed_jobs_task`` daily 03:00 NZT.

Phase 3b seams: the enqueue side of the JobSummary.pdf refresh is fully live
(``Job.save()``/CostLine writes call ``request_job_summary_pdf_refresh``);
task BODIES whose services are later sub-slices raise ``NotImplementedError``
loudly when a worker executes them, so nothing silently no-ops.

v1 wrapped ``refresh_job_summary_pdfs_task`` in ``cast(Any, shared_task(...))``
to type ``.apply_async``; celery-types now types ``shared_task`` directly, so
that workaround is dropped (same call as apps/crm/tasks.py).
"""

import logging

from celery import shared_task
from django.core.cache import caches
from django.db import close_old_connections, transaction

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
        close_old_connections()
        # Body lands with the job-files sub-slice; fail loudly, never no-op.
        raise NotImplementedError("Phase 3b: apps.job.services.file_service (job-files sub-slice)")
    except Exception as exc:
        logger.exception("Error creating thumbnail for job file %s.", job_file_id)
        persist_app_error(exc, AppErrorContext(additional_context={"job_file_id": job_file_id}))
        raise


@shared_task(name="apps.job.tasks.refresh_job_summary_pdfs_task")
def refresh_job_summary_pdfs_task(limit: int = JOB_SUMMARY_PDF_REFRESH_BATCH_SIZE) -> None:
    """Refresh a bounded batch of missing/stale disaster-recovery PDFs.

    The queue/lock bookkeeping is live so ``Job.save()`` works tree-wide; the
    PDF generation itself needs ``workshop_pdf_service`` (later sub-slice), so
    execution fails loudly with the phase marker until that lands.
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

    try:
        cache.delete(JOB_SUMMARY_PDF_REFRESH_QUEUED_KEY)
        # TODO(Phase 3b-3): restore v1's full body (v1 tasks.py:132-161), NOT
        # just the refresh call — after JobSummaryPdfService.refresh_stale(limit)
        # v1 computed follow_up_required = remaining or bool(cache.get(QUEUED_KEY))
        # and, when set, chained _queue_job_summary_pdf_refresh(countdown=0) in a
        # post-finally block so large backlogs drain batch by batch.
        raise NotImplementedError(
            "Phase 3b-3: workshop_pdf_service (JobSummaryPdfService.refresh_stale not ported)"
        )
    except Exception as exc:
        cache.delete(JOB_SUMMARY_PDF_REFRESH_QUEUED_KEY)
        logger.exception("Error refreshing JobSummary.pdf files.")
        persist_app_error(exc, AppErrorContext(additional_context={"limit": limit}))
        raise
    finally:
        cache.delete(JOB_SUMMARY_PDF_REFRESH_RUNNING_KEY)


@shared_task(name="apps.job.tasks.set_paid_flag_task")
def set_paid_flag_task() -> None:
    """Mark completed jobs with fully paid invoices as 'paid'.

    Beat-scheduled daily 02:00 NZT. Runs before auto_archive_completed_jobs
    so freshly marked jobs become eligible for archival.
    """
    logger.info("Running set_paid_flag_task.")
    try:
        close_old_connections()
        raise NotImplementedError(
            "Phase 3b: apps.job.services.paid_flag_service (month-end sub-slice)"
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
        close_old_connections()
        raise NotImplementedError(
            "Phase 3b: apps.job.services.auto_archive_service (month-end sub-slice)"
        )
    except Exception as exc:
        logger.exception("Error during auto_archive_completed_jobs_task.")
        persist_app_error(exc)
        raise
