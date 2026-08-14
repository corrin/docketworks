"""Celery worker for the long-running Xero sync.

Lives in its own module (not in ``apps/xero/tasks.py``) so it can be
imported by both ``XeroSyncService`` (the dispatcher, which calls
``.delay()``) and re-exported from ``tasks.py`` without forming an import
cycle.

Under ``XERO_READONLY`` the whole run is suppressed — v1 expressed this as
the readonly provider's ``run_full_sync`` override; v2's worker calls the
sync engine directly, so the gate lives here. Blanket-blocked on purpose:
the full sync both pushes local stock to Xero and pulls tenant data into
the local DB, and neither belongs in a read-only test run.
"""

import logging

from celery import shared_task
from django.conf import settings
from django.core.cache import caches
from django.utils import timezone

from apps.accounting.registry import is_accounting_enabled
from apps.core.errors import persist_app_error
from apps.xero.client import XeroQuotaFloorReached
from apps.xero.sync_constants import SYNC_STATUS_KEY, release_sync_lock

# The writer (this worker) and the readers (gunicorn SSE view) run in
# different processes, so route Xero sync state through the Redis-backed
# "shared" alias.
_sync_cache = caches["shared"]

logger = logging.getLogger(__name__)


def _append_sync_failure_messages(
    *,
    messages_key: str,
    task_id: str,
    message: str,
    sync_status: str,
    app_error_id: str | None = None,
) -> None:
    msgs = _sync_cache.get(messages_key, [])
    # An abort is operational, not an error: the SSE stream derives its
    # terminal sync_status from error-severity messages, and an aborted run
    # must not read back as a failed one.
    severity = "warning" if sync_status == "aborted" else "error"
    error_payload: dict[str, object] = {
        "datetime": timezone.now().isoformat(),
        "entity": "sync",
        "severity": severity,
        "message": message,
        "progress": None,
        "task_id": task_id,
    }
    if app_error_id:
        error_payload["error_id"] = app_error_id
    msgs.append(error_payload)
    msgs.append(
        {
            "datetime": timezone.now().isoformat(),
            "entity": "sync",
            "severity": "info",
            "message": "Sync stream ended",
            "sync_status": sync_status,
            "progress": None,
            "task_id": task_id,
        }
    )
    _sync_cache.set(messages_key, msgs, timeout=86400)


def _append_abort_marker(messages_key: str, task_id: str, message: str) -> None:
    msgs = _sync_cache.get(messages_key, [])
    msgs.append(
        {
            "datetime": timezone.now().isoformat(),
            "entity": "sync",
            "severity": "warning",
            "message": message,
            "progress": None,
            "task_id": task_id,
            "sync_status": "aborted",
        }
    )
    _sync_cache.set(messages_key, msgs, timeout=86400)


@shared_task(name="apps.xero.tasks.xero_sync_task")
def xero_sync_task(  # noqa: C901, PLR0915 -- one worker owns gates, event relay, and every terminal marker
    task_id: str,
) -> None:
    """Execute one Xero sync run end-to-end.

    Dispatched by ``XeroSyncService.start_sync()`` after it has acquired the
    Redis lock and seeded the message-buffer cache keys. django_celery_results
    records the real outcome of each run (SUCCESS, FAILURE-with-traceback,
    REVOKED on worker crash).

    The dispatcher holds the SYNC_STATUS_KEY lock (value = this task id)
    until the finally block releases it — and the release is owner-checked,
    so a redelivered or expired-lock task cannot free a newer run's lock.
    Tenant is implicit (single-tenant per Django instance —
    CompanyDefaults.get_solo()), consistent with the rest of the Xero code
    path.
    """
    # Call-time import: the sync engine pulls in the whole transform tree.
    from apps.xero.sync import ENTITY_CONFIGS, synchronise_xero_data  # noqa: PLC0415

    messages_key = f"xero_sync_messages_{task_id}"
    current_key = f"xero_sync_current_entity_{task_id}"
    progress_key = f"xero_sync_entity_progress_{task_id}"
    overall_key = f"xero_sync_overall_progress_{task_id}"

    # Redelivery guard: acks_late + a Redis visibility timeout shorter than a
    # deep sync means the broker CAN redeliver a live run's message. The lock
    # value is the owning task id; a delivery that no longer owns the lock
    # must not run a second concurrent sync (or touch the message buffer).
    if _sync_cache.get(SYNC_STATUS_KEY) != task_id:
        logger.warning("Xero sync task %s skipped: lock not held (redelivery or expiry)", task_id)
        return

    try:
        if settings.XERO_READONLY:
            # v1 parity: XeroReadOnlyProvider.run_full_sync skipped the whole
            # run with this message.
            _append_abort_marker(messages_key, task_id, "Sync skipped: XERO_READONLY is set")
            logger.info("Xero sync task %s skipped: XERO_READONLY", task_id)
            return

        if not is_accounting_enabled():
            _append_abort_marker(
                messages_key, task_id, "Xero sync skipped: enable_xero_sync is False"
            )
            logger.info("Xero sync task %s skipped: sync disabled", task_id)
            return

        msgs = _sync_cache.get(messages_key, [])
        processed = 0
        # +2: the pay_items pseudo-entity the orchestrator emits first, and
        # the stock_local_to_xero push that also emits a Completed event.
        total_entities = len(ENTITY_CONFIGS) + 2

        for message in synchronise_xero_data():
            enriched: dict[str, object] = dict(message)
            enriched["task_id"] = task_id

            if "progress" in enriched and enriched["progress"] is not None:
                enriched["entity_progress"] = enriched.pop("progress")

            entity = enriched.get("entity")
            if entity and entity != "sync":
                _sync_cache.set(current_key, entity, timeout=86400)
                if "entity_progress" in enriched:
                    _sync_cache.set(progress_key, enriched["entity_progress"], timeout=86400)
                if enriched.get("status") == "Completed":
                    processed += 1

            overall = processed / total_entities if total_entities > 0 else 0.0
            enriched["overall_progress"] = round(overall, 3)
            _sync_cache.set(overall_key, overall, timeout=86400)

            if "recordsUpdated" in enriched:
                enriched["records_updated"] = enriched["recordsUpdated"]

            msgs.append(enriched)
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
        logger.info("Completed Xero sync task %s", task_id)

    # deliberate-swallow: operational abort, not a defect. Do NOT
    # persist_app_error (24+ rows/day at the floor would be noise), do not
    # re-raise (the task ran and decided to abort cleanly — TaskResult
    # SUCCESS is correct). The "aborted" marker is what distinguishes this
    # from a clean run for the UI, scheduler and monitoring.
    except XeroQuotaFloorReached as exc:
        logger.warning("Xero sync %s aborted: %s", task_id, exc)
        _append_sync_failure_messages(
            messages_key=messages_key,
            task_id=task_id,
            message=f"Sync aborted: {exc}",
            sync_status="aborted",
        )

    except Exception as exc:
        err = persist_app_error(exc)
        _append_sync_failure_messages(
            messages_key=messages_key,
            task_id=task_id,
            message=f"Error during sync: {exc}",
            sync_status="error",
            app_error_id=str(err.id),
        )
        raise

    finally:
        _sync_cache.delete(current_key)
        _sync_cache.delete(progress_key)
        release_sync_lock(task_id)
