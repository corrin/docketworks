# workflow/services/xero_sync_service.py

import logging
import uuid

from django.core.cache import cache, caches

from apps.workflow.accounting.registry import get_provider
from apps.workflow.api.xero.constants import TENANT_ID_CACHE_KEY
from apps.workflow.exceptions import (
    NoValidXeroTokenError,
    XeroSyncAlreadyRunningError,
)
from apps.workflow.services.xero_sync_constants import LOCK_TIMEOUT, SYNC_STATUS_KEY
from apps.workflow.services.xero_sync_worker import xero_sync_task

logger = logging.getLogger("xero")

# Sync state (lock + per-task message buffer / progress) lives on "shared"
# (Redis) because the writer (Celery worker) and the readers (gunicorn SSE
# views) run in different processes. TENANT_ID_CACHE_KEY stays on the
# default per-process cache — it's a discovery cache, refilled cheaply.
_sync_cache = caches["shared"]


class XeroSyncService:
    """Accounting sync service that dispatches sync runs to Celery.

    Works with any configured accounting provider via the provider registry.
    """

    def __init__(self, tenant_id: str | None = None):
        """Only used by webhooks. For full sync routine, we keep the static methods."""
        provider = get_provider()
        token = provider.get_valid_token()
        if not token:
            raise ValueError("No valid accounting token found")
        self.token = token

        if tenant_id:
            self.tenant_id = tenant_id
        else:
            self.tenant_id = cache.get(TENANT_ID_CACHE_KEY)
            if not self.tenant_id:
                from apps.workflow.api.xero.auth import get_tenant_id_from_connections

                self.tenant_id = get_tenant_id_from_connections()
        if not self.tenant_id:
            raise ValueError("No tenant ID found in cache or connections")
        cache.set(TENANT_ID_CACHE_KEY, self.tenant_id, timeout=1800)

    @staticmethod
    def start_sync() -> str:
        """Acquire the lock and dispatch a Celery task for the sync run.

        The actual sync work runs in ``apps.workflow.tasks.xero_sync_task``
        — moving it out of a detached thread means django_celery_results
        records the true outcome (SUCCESS, FAILURE-with-traceback, or
        REVOKED on worker crash) instead of the dispatch-only success the
        thread model produced.

        Returns the dispatched task_id on success. Raises
        ``XeroSyncAlreadyRunningError`` (with the active task_id) when
        another sync holds the lock, and ``NoValidXeroTokenError`` when
        the lock was acquired but no valid Xero token is available.
        Each failure mode has its own typed channel so callers (Beat
        tasks, views) react distinctly without inspecting an overloaded
        return shape.
        """
        task_id = str(uuid.uuid4())
        got_lock = _sync_cache.add(
            SYNC_STATUS_KEY,
            task_id,
            timeout=LOCK_TIMEOUT,
        )

        if not got_lock:
            active_task_id = _sync_cache.get(SYNC_STATUS_KEY)
            logger.info(
                "Sync already running (task_id=%s); not starting a new one",
                active_task_id,
            )
            raise XeroSyncAlreadyRunningError(active_task_id)

        provider = get_provider()
        token = provider.get_valid_token()
        if not token:
            logger.error("No valid Xero token found")
            _sync_cache.delete(SYNC_STATUS_KEY)
            raise NoValidXeroTokenError("No valid Xero token found")

        _sync_cache.set(f"xero_sync_messages_{task_id}", [], timeout=86400)
        _sync_cache.set(f"xero_sync_current_entity_{task_id}", None, timeout=86400)
        _sync_cache.set(f"xero_sync_entity_progress_{task_id}", 0.0, timeout=86400)

        try:
            xero_sync_task.delay(task_id)
        except Exception:
            # Broker unavailable — release the lock so the next attempt can
            # try. Don't persist here; the caller (Beat task or view) owns
            # the AlreadyLoggedException pattern.
            _sync_cache.delete(SYNC_STATUS_KEY)
            raise

        logger.info("Dispatched Xero sync task %s", task_id)
        return task_id

    @staticmethod
    def get_messages(task_id, since_index=0):
        """Return sync messages for ``task_id`` starting from ``since_index``."""
        msgs = _sync_cache.get(f"xero_sync_messages_{task_id}", [])
        return msgs[since_index:] if since_index < len(msgs) else []

    @staticmethod
    def get_current_entity(task_id):
        """Get the entity currently being processed for ``task_id``."""
        return _sync_cache.get(f"xero_sync_current_entity_{task_id}")

    @staticmethod
    def get_entity_progress(task_id):
        """Retrieve progress (0.0-1.0) for ``task_id``."""
        return _sync_cache.get(f"xero_sync_entity_progress_{task_id}", 0.0)

    @staticmethod
    def get_active_task_id():
        """Return the task ID of the running sync if any."""
        return _sync_cache.get(SYNC_STATUS_KEY)
