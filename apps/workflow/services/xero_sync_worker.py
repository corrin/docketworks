"""Celery worker for the long-running Xero sync.

Lives in its own module (not in ``apps.workflow.tasks``) so it can be
imported by both ``XeroSyncService`` (the dispatcher, which calls
``.delay()``) and re-exported from ``apps.workflow.tasks`` without
forming an import cycle. The Celery-registered task name stays
``apps.workflow.tasks.xero_sync_task`` (set explicitly on the decorator)
so beat schedules and historical TaskResult rows are unaffected.
"""

import logging

from celery import shared_task
from django.core.cache import caches
from django.utils import timezone

from apps.workflow.exceptions import AlreadyLoggedException, XeroQuotaFloorReached
from apps.workflow.services.error_persistence import persist_app_error
from apps.workflow.services.xero_sync_constants import SYNC_STATUS_KEY

# The writer (this worker) and the readers (gunicorn SSE view) run in
# different processes, so route Xero sync state through the Redis-backed
# "shared" alias.
_sync_cache = caches["shared"]

# Same logger name as before the extraction so existing log filters and
# dashboards keep matching.
scheduler_logger = logging.getLogger("apps.workflow.tasks")


@shared_task(name="apps.workflow.tasks.xero_sync_task")
def xero_sync_task(task_id: str) -> None:
    """Execute one Xero sync run end-to-end.

    Dispatched by ``XeroSyncService.start_sync()`` after it has acquired the
    Redis lock and seeded the message-buffer cache keys. The body is the
    sync loop that used to run in a detached ``threading.Thread`` — moving
    it here means django_celery_results records the real outcome of each
    run (SUCCESS, FAILURE-with-traceback, REVOKED on worker crash) instead
    of the dispatch-only success the thread model produced.

    Idempotent via the SYNC_STATUS_KEY lock acquired before dispatch:
    double-delivery short-circuits because the lock is still held until the
    finally block runs. Tenant is implicit (single-tenant per Django
    instance — CompanyDefaults.get_solo()), consistent with the rest of
    the Xero code path.
    """
    from apps.workflow.accounting.registry import get_provider

    provider = get_provider()
    messages_key = f"xero_sync_messages_{task_id}"
    current_key = f"xero_sync_current_entity_{task_id}"
    progress_key = f"xero_sync_entity_progress_{task_id}"
    overall_key = f"xero_sync_overall_progress_{task_id}"

    try:
        msgs = _sync_cache.get(messages_key, [])
        processed = 0
        total_entities = provider.get_sync_entity_count()

        for message in provider.run_full_sync():
            message["task_id"] = task_id

            if "progress" in message and message["progress"] is not None:
                message["entity_progress"] = message.pop("progress")

            entity = message.get("entity")
            if entity and entity != "sync":
                _sync_cache.set(current_key, entity, timeout=86400)
                if "entity_progress" in message:
                    _sync_cache.set(
                        progress_key, message["entity_progress"], timeout=86400
                    )
                if message.get("status") == "Completed":
                    processed += 1

            overall = processed / total_entities if total_entities > 0 else 0.0
            message["overall_progress"] = round(overall, 3)
            _sync_cache.set(overall_key, overall, timeout=86400)

            if "recordsUpdated" in message:
                message["records_updated"] = message["recordsUpdated"]

            msgs.append(message)
            _sync_cache.set(messages_key, msgs, timeout=86400)

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
        _sync_cache.set(messages_key, msgs, timeout=86400)
        scheduler_logger.info("Completed Xero sync task %s", task_id)

    except XeroQuotaFloorReached as exc:
        # Operational abort, not a defect. Do NOT persist_app_error
        # (24+ rows/day at the floor would be noise). Final marker is
        # sync_status:"aborted" — distinct from "success" so the UI,
        # scheduler, and monitoring don't mistake this for a clean run.
        scheduler_logger.warning("Xero sync %s aborted: %s", task_id, exc)
        msgs = _sync_cache.get(messages_key, [])
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
        _sync_cache.set(messages_key, msgs, timeout=86400)
        # Do not re-raise; abort is operational and the finally clears the
        # lock cleanly. TaskResult records SUCCESS, which is correct for
        # "the task ran and decided to abort cleanly".

    except AlreadyLoggedException:
        raise
    except Exception as exc:
        msgs = _sync_cache.get(messages_key, [])
        msgs.append(
            {
                "datetime": timezone.now().isoformat(),
                "entity": "sync",
                "severity": "error",
                "message": f"Error during sync: {exc}",
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
        _sync_cache.set(messages_key, msgs, timeout=86400)
        err = persist_app_error(exc)
        raise AlreadyLoggedException(exc, err.id) from exc

    finally:
        _sync_cache.delete(current_key)
        _sync_cache.delete(progress_key)
        _sync_cache.delete(SYNC_STATUS_KEY)
