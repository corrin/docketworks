"""Celery tasks for the operations app.

Beat-scheduled workshop schedule recomputation.
"""

import logging

from celery import shared_task
from django.db import close_old_connections

from apps.workflow.services.error_persistence import persist_app_error

logger = logging.getLogger("apps.operations.tasks")


@shared_task(name="apps.operations.tasks.recompute_workshop_schedule_task")
def recompute_workshop_schedule_task() -> None:
    """Recompute and persist the workshop schedule forecast.

    Beat-scheduled hourly. On failure, calls persist_app_error and returns
    without raising so the next scheduled run still happens and the last
    successful forecast remains intact.
    """
    logger.info("Starting workshop schedule recomputation.")
    try:
        close_old_connections()
        from apps.operations.services.scheduler_service import run_workshop_schedule

        run_workshop_schedule()
        logger.info("Workshop schedule recomputation completed successfully.")
    except Exception as exc:
        persist_app_error(exc)
        logger.error("Workshop schedule recomputation failed: %s", exc, exc_info=True)
