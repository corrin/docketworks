"""Celery tasks for the diagnostics application.

Task names are an operational contract because Beat schedule entries reference
them. Schedules are declared in ``config/celery.py``; task functions belong here.
"""

import logging

from celery import shared_task
from django.db import close_old_connections

from apps.core.errors import persist_app_error
from apps.core.models import CompanyDefaults
from apps.diagnostics.services.session_replay_service import purge_old_recordings

logger = logging.getLogger("apps.diagnostics.tasks")


@shared_task(name="apps.diagnostics.tasks.purge_old_session_replays_task")
def purge_old_session_replays_task() -> None:
    """Delete session replays past the retention window, payloads included.

    A replay is an unredacted recording of somebody's screen, so retention is
    the feature's only privacy control and this task is what enforces it.
    Chunk rows go with their recording via CASCADE and their files go with
    them (``delete_recordings``); an AppError that referenced a purged
    recording keeps the error and loses only the link (SET_NULL on
    ``AppError.session_replay``).
    """
    logger.info("Running purge_old_session_replays_task.")
    try:
        close_old_connections()
        retention_days = CompanyDefaults.get_solo().session_replay_retention_days
        deleted = purge_old_recordings(retention_days=retention_days)
        logger.info(
            "Deleted %s session replay rows using %s day retention.",
            deleted,
            retention_days,
        )
    except Exception as exc:
        logger.exception("Error during session replay purge.")
        persist_app_error(exc)
        raise
