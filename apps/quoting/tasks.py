"""Celery tasks for the quoting app.

Beat-scheduled supplier-price scraping job. Per ADR 0024: tasks are
idempotent and tenant-aware; failures persist via AppError (ADR 0019).
"""

import logging

from celery import shared_task
from django.core.management import call_command
from django.db import close_old_connections

from apps.workflow.exceptions import AlreadyLoggedException
from apps.workflow.services.error_persistence import persist_app_error

logger = logging.getLogger("apps.quoting.tasks")


@shared_task(name="apps.quoting.tasks.run_all_scrapers_task")
def run_all_scrapers_task() -> None:
    """Run all supplier-price scrapers. Beat-scheduled Sunday 15:00 NZT.

    Delegates to the existing `run_scrapers` management command with
    `--refresh-old` so existing products are updated, not just new ones.
    """
    logger.info("Attempting to run all scrapers via scheduled task.")
    try:
        close_old_connections()
        call_command("run_scrapers", refresh_old=True)
        logger.info("Successfully completed scheduled scraper run.")
    except AlreadyLoggedException:
        raise
    except Exception as exc:
        logger.error("Error during scheduled scraper run: %s", exc, exc_info=True)
        app_error = persist_app_error(exc)
        raise AlreadyLoggedException(exc, app_error.id) from exc
