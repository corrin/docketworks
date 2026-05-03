# workflow/services/xero_sync_service.py

import logging
import threading
import uuid

from django.core.cache import cache
from django.utils import timezone

from apps.workflow.accounting.registry import get_provider
from apps.workflow.api.xero.constants import TENANT_ID_CACHE_KEY
from apps.workflow.exceptions import XeroQuotaFloorReached

logger = logging.getLogger("xero")


class XeroSyncService:
    """Accounting sync service that manages synchronisation threads.

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

    LOCK_TIMEOUT = 60 * 60 * 4  # 4 hours
    SYNC_STATUS_KEY = "xero_sync_status"

    @staticmethod
    def start_sync():
        """Launch a sync thread if none is running.

        Returns:
            tuple[str | None, bool]: (task_id, started)
        """
        task_id = str(uuid.uuid4())
        # Atomic lock acquire and store task ID
        got_lock = cache.add(
            XeroSyncService.SYNC_STATUS_KEY,
            task_id,
            timeout=XeroSyncService.LOCK_TIMEOUT,
        )

        if not got_lock:
            logger.info("Sync already running; not starting a new one")
            # Retrieve the task ID of the currently running sync
            active_task_id = cache.get(XeroSyncService.SYNC_STATUS_KEY)
            return active_task_id, False

        # Validate token
        provider = get_provider()
        token = provider.get_valid_token()
        if not token:
            logger.error("No valid Xero token found")
            cache.delete(
                XeroSyncService.SYNC_STATUS_KEY
            )  # Release lock if token is invalid
            return None, False

        # Prepare task (message and progress keys still use task_id)
        cache.set(f"xero_sync_messages_{task_id}", [], timeout=86400)
        cache.set(f"xero_sync_current_entity_{task_id}", None, timeout=86400)
        cache.set(f"xero_sync_entity_progress_{task_id}", 0.0, timeout=86400)

        # Launch
        thread = threading.Thread(
            target=XeroSyncService.run_sync, args=[task_id], daemon=True
        )
        thread.start()

        logger.info(f"Started Xero sync with task ID {task_id}")
        return task_id, True

    @staticmethod
    def run_sync(task_id):
        """Execute the sync and record messages under ``task_id``."""
        from apps.workflow.accounting.registry import get_provider

        provider = get_provider()

        messages_key = f"xero_sync_messages_{task_id}"
        current_key = f"xero_sync_current_entity_{task_id}"
        progress_key = f"xero_sync_entity_progress_{task_id}"
        overall_key = f"xero_sync_overall_progress_{task_id}"

        try:
            msgs = cache.get(messages_key, [])
            processed = 0
            total_entities = provider.get_sync_entity_count()

            for message in provider.run_full_sync():
                message["task_id"] = task_id

                # Always propagate 'entity_progress' if there is 'progress'
                if "progress" in message and message["progress"] is not None:
                    message["entity_progress"] = message.pop("progress")

                # Track entity/progress
                entity = message.get("entity")
                if entity and entity != "sync":
                    cache.set(current_key, entity, timeout=86400)
                    if "entity_progress" in message:
                        cache.set(
                            progress_key, message["entity_progress"], timeout=86400
                        )
                    if message.get("status") == "Completed":
                        processed += 1

                overall = processed / total_entities if total_entities > 0 else 0.0
                message["overall_progress"] = round(overall, 3)
                cache.set(overall_key, overall, timeout=86400)

                if "recordsUpdated" in message:
                    message["records_updated"] = message["recordsUpdated"]

                msgs.append(message)
                cache.set(messages_key, msgs, timeout=86400)

            # Final marker
            msgs.append(
                {
                    "datetime": timezone.now().isoformat(),
                    "entity": "sync",
                    "severity": "info",
                    "message": "Sync stream ended",
                    "overall_progress": 1.0,
                    "entity_progress": 1.0,
                    "sync_status": "success",
                    "task_id": task_id,
                }
            )
            cache.set(messages_key, msgs, timeout=86400)
            logger.info(f"Completed Xero sync task {task_id}")

        except XeroQuotaFloorReached as exc:
            # Operational abort, not a defect. Do NOT persist_app_error
            # (would write 24+ rows/day at the floor). Final marker is
            # sync_status:"aborted" — distinct from "success" so the UI,
            # scheduler, and monitoring don't mistake this for a clean run.
            logger.warning("Xero sync %s aborted: %s", task_id, exc)
            msgs = cache.get(messages_key, [])
            msgs.append(
                {
                    "datetime": timezone.now().isoformat(),
                    "entity": "sync",
                    "severity": "error",
                    "message": f"Sync aborted: {exc}",
                    "progress": None,
                    "task_id": task_id,
                }
            )
            msgs.append(
                {
                    "datetime": timezone.now().isoformat(),
                    "entity": "sync",
                    "severity": "info",
                    "message": "Sync stream ended",
                    "sync_status": "aborted",
                    "progress": None,
                    "task_id": task_id,
                }
            )
            cache.set(messages_key, msgs, timeout=86400)
            # Don't re-raise — abort is operational. The finally below
            # releases the lock cleanly.
        except Exception as e:
            from apps.workflow.services.error_persistence import persist_app_error

            persist_app_error(e)
            logger.error(f"Error during Xero sync task {task_id}: {e}", exc_info=True)
            msgs = cache.get(messages_key, [])
            msgs.append(
                {
                    "datetime": timezone.now().isoformat(),
                    "entity": "sync",
                    "severity": "error",
                    "message": f"Error during sync: {e}",
                    "progress": None,
                    "task_id": task_id,
                }
            )
            msgs.append(
                {
                    "datetime": timezone.now().isoformat(),
                    "entity": "sync",
                    "severity": "info",
                    "message": "Sync stream ended",
                    "progress": None,
                    "task_id": task_id,
                }
            )
            cache.set(messages_key, msgs, timeout=86400)
            # Re-raise the exception to ensure the calling process is aware of the failure
            # We are about to crash, so we need to clean up the lock
            cache.delete(current_key)
            cache.delete(progress_key)
            cache.delete(
                XeroSyncService.SYNC_STATUS_KEY
            )  # Release lock and clear task ID
            raise e

        finally:
            cache.delete(current_key)
            cache.delete(progress_key)
            cache.delete(
                XeroSyncService.SYNC_STATUS_KEY
            )  # Release lock and clear task ID

    @staticmethod
    def get_messages(task_id, since_index=0):
        """Return sync messages for ``task_id`` starting from ``since_index``."""
        msgs = cache.get(f"xero_sync_messages_{task_id}", [])
        return msgs[since_index:] if since_index < len(msgs) else []

    @staticmethod
    def get_current_entity(task_id):
        """Get the entity currently being processed for ``task_id``."""
        return cache.get(f"xero_sync_current_entity_{task_id}")

    @staticmethod
    def get_entity_progress(task_id):
        """Retrieve progress (0.0-1.0) for ``task_id``."""
        return cache.get(f"xero_sync_entity_progress_{task_id}", 0.0)

    @staticmethod
    def get_active_task_id():
        """Return the task ID of the running sync if any."""
        return cache.get(XeroSyncService.SYNC_STATUS_KEY)
