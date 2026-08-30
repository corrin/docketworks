"""Celery tasks for the diagnostics application.

Task names are an operational contract because Beat schedule entries reference
them. Schedules are declared in ``config/celery.py``; task functions belong here.
"""

import logging
from datetime import timedelta

from celery import shared_task
from django.db import close_old_connections
from django.utils import timezone

from apps.core.errors import persist_app_error
from apps.diagnostics.models import SessionReplayRecording

logger = logging.getLogger("apps.diagnostics.tasks")

# v1 required this via the SESSION_REPLAY_RETENTION_DAYS env var, but every
# environment set 14 — the knob never varied. Codex: the task is deliberately
# not scheduled until replay ingestion lands; retention returns with that
# schedule.
SESSION_REPLAY_RETENTION_DAYS = 14


@shared_task(name="apps.diagnostics.tasks.purge_old_session_replays_task")
def purge_old_session_replays_task() -> None:
    """Purge session replays past retention once ingestion is available.

    v1's purge also unlinked each chunk's payload file under
    SESSION_REPLAY_STORAGE_ROOT; v2 has no such setting and no replay
    ingestion (rrweb is not in the frontend), so the rows are the whole store
    to prune. Chunks go with their recording via CASCADE, and an AppError that
    references a purged recording keeps the error and loses only the link
    (SET_NULL on ``AppError.session_replay``). Replay capture must add the Beat
    schedule and make its storage layer own payload cleanup with this row purge.
    """
    logger.info("Running purge_old_session_replays_task.")
    try:
        close_old_connections()
        cutoff = timezone.now() - timedelta(days=SESSION_REPLAY_RETENTION_DAYS)
        deleted, _ = SessionReplayRecording.objects.filter(started_at__lt=cutoff).delete()
        logger.info(
            "Deleted %s session replay rows using %s day retention.",
            deleted,
            SESSION_REPLAY_RETENTION_DAYS,
        )
    except Exception as exc:
        logger.exception("Error during session replay purge.")
        persist_app_error(exc)
        raise
