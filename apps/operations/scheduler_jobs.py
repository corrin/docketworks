import logging

from django.db import close_old_connections

from apps.workflow.services.error_persistence import persist_app_error

logger = logging.getLogger(__name__)


def recompute_workshop_schedule() -> None:
    """
    Recompute and persist the workshop schedule forecast.

    Runs on a schedule. On failure, calls persist_app_error and returns
    without raising so the scheduler keeps running and the last successful
    forecast remains intact.
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
        # Do NOT re-raise — keep the scheduler running and preserve last good forecast
