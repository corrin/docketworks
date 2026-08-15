"""Dispatch and observe Xero sync runs.

Sync state (lock + per-task message buffer / progress) lives on the "shared"
Redis alias because the writer (Celery worker) and the readers (gunicorn SSE
views) run in different processes. The lock VALUE is the task id, so readers
can attach to a run they didn't start.
"""

import logging
import uuid
from dataclasses import dataclass
from typing import Literal

from django.core.cache import caches

from apps.accounting.registry import get_provider
from apps.xero.sync_constants import LOCK_TIMEOUT, SYNC_STATUS_KEY, release_sync_lock
from apps.xero.sync_worker import xero_sync_task

logger = logging.getLogger(__name__)

_sync_cache = caches["shared"]


@dataclass(frozen=True)
class XeroSyncStartResult:
    """Outcome of attempting to dispatch a Xero sync run."""

    started: bool
    reason: Literal["started", "already_running", "no_valid_token"]
    task_id: str | None = None


class XeroSyncService:
    """Dispatches sync runs to Celery and reads their progress state."""

    @staticmethod
    def start_sync() -> XeroSyncStartResult:
        """Acquire the lock and dispatch a Celery task for the sync run.

        Returns an explicit outcome for expected dispatch states. Broker
        failures still raise because they are defects after the lock has
        been acquired.
        """
        task_id = str(uuid.uuid4())
        got_lock = _sync_cache.add(SYNC_STATUS_KEY, task_id, timeout=LOCK_TIMEOUT)

        if not got_lock:
            active_task_id = _sync_cache.get(SYNC_STATUS_KEY)
            logger.info("Sync already running (task_id=%s); not starting a new one", active_task_id)
            return XeroSyncStartResult(
                started=False, reason="already_running", task_id=active_task_id
            )

        # Every rollback below releases through release_sync_lock rather than
        # deleting the key: a token check slow enough to outlive the lease
        # would otherwise have this attempt delete the NEXT run's lock on its
        # way out — the exact concurrent sync the lock exists to prevent.
        try:
            provider = get_provider()
            token = provider.get_valid_token()
        except Exception:
            release_sync_lock(task_id)
            raise
        if not token:
            logger.error("No valid Xero token found")
            release_sync_lock(task_id)
            return XeroSyncStartResult(started=False, reason="no_valid_token")

        _sync_cache.set(f"xero_sync_messages_{task_id}", [], timeout=86400)
        _sync_cache.set(f"xero_sync_current_entity_{task_id}", None, timeout=86400)
        _sync_cache.set(f"xero_sync_entity_progress_{task_id}", 0.0, timeout=86400)

        try:
            xero_sync_task.delay(task_id)
        except Exception:
            # Broker unavailable — release the lock so the next attempt can
            # try. Don't persist here; the caller (beat task or view) owns
            # error persistence.
            release_sync_lock(task_id)
            raise

        logger.info("Dispatched Xero sync task %s", task_id)
        return XeroSyncStartResult(started=True, reason="started", task_id=task_id)

    @staticmethod
    def get_messages(task_id: str, since_index: int = 0) -> list[dict[str, object]]:
        """Return sync messages for ``task_id`` starting from ``since_index``."""
        msgs: list[dict[str, object]] = _sync_cache.get(f"xero_sync_messages_{task_id}", [])
        return msgs[since_index:] if since_index < len(msgs) else []

    @staticmethod
    def get_current_entity(task_id: str) -> str | None:
        """Get the entity currently being processed for ``task_id``."""
        entity: str | None = _sync_cache.get(f"xero_sync_current_entity_{task_id}")
        return entity

    @staticmethod
    def get_entity_progress(task_id: str) -> float:
        """Retrieve progress (0.0-1.0) for ``task_id``."""
        progress: float = _sync_cache.get(f"xero_sync_entity_progress_{task_id}", 0.0)
        return progress

    @staticmethod
    def get_active_task_id() -> str | None:
        """Return the task ID of the running sync if any."""
        task_id: str | None = _sync_cache.get(SYNC_STATUS_KEY)
        return task_id
