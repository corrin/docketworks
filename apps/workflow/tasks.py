"""Celery tasks for the workflow app.

Tasks here follow ADR 0024: idempotent, tenant-aware (tenant_id is an
explicit argument), write-side (results land in the DB, not in a result
backend). `.delay().get()` is forbidden.
"""

import logging
from typing import Any, Dict

from celery import shared_task
from django.conf import settings
from django.core.cache import caches
from django.db import close_old_connections
from django.utils import timezone

from apps.workflow.api.xero.client import quota_floor_breached
from apps.workflow.api.xero.sync import sync_single_contact, sync_single_invoice
from apps.workflow.exceptions import AlreadyLoggedException, XeroQuotaFloorReached
from apps.workflow.models import CompanyDefaults
from apps.workflow.services.error_persistence import persist_app_error
from apps.workflow.services.xero_sync_service import XeroSyncService

logger = logging.getLogger("xero")
scheduler_logger = logging.getLogger("apps.workflow.tasks")

# Xero sync state crosses processes (this Celery worker writes; the gunicorn
# SSE view reads), so route through the Redis-backed "shared" alias. Other
# tasks in this module don't share state cross-process and can use the
# default per-process cache.
_sync_cache = caches["shared"]

CELERY_HEALTH_CHECK_SENTINEL = "docketworks-celery-ok"


@shared_task(name="apps.workflow.tasks.celery_health_check")
def celery_health_check() -> str:
    """Return a deterministic sentinel — proof the broker, worker, and task
    autodiscovery are all wired up. Used in unit tests and in the deploy
    runbook for a manual round-trip check."""
    return CELERY_HEALTH_CHECK_SENTINEL


@shared_task(name="apps.workflow.tasks.process_xero_webhook_event")
def process_xero_webhook_event(tenant_id: str, event: Dict[str, Any]) -> None:
    """Sync a single Xero resource referenced by a webhook event.

    Replaces the synchronous in-handler processing that exceeded Xero's 5s
    redelivery timeout, triggered retries, and drained the day quota
    (Trello card #291).

    Idempotent: ``sync_single_{contact,invoice}`` use ``update_or_create``
    keyed on the Xero ID, so re-execution converges on the same DB state.
    Tenant-aware: ``tenant_id`` is the explicit task argument; never read
    from process state. Write-side: callers do not read a return value.
    """
    if quota_floor_breached(settings.XERO_AUTOMATED_DAY_FLOOR):
        logger.warning(
            "Xero day quota at floor (%s) — skipping webhook event %s",
            settings.XERO_AUTOMATED_DAY_FLOOR,
            event,
        )
        # Return (do not raise) — raising would make Celery retry indefinitely.
        return

    event_category = event.get("eventCategory")
    resource_id = event.get("resourceId")

    if not event_category or not resource_id:
        logger.error("Invalid webhook event - missing required fields: %s", event)
        return

    company_defaults = CompanyDefaults.get_solo()
    if company_defaults.xero_tenant_id != tenant_id:
        logger.warning(
            "Webhook event for wrong tenant %s, expected %s",
            tenant_id,
            company_defaults.xero_tenant_id,
        )
        return

    try:
        sync_service = XeroSyncService(tenant_id=tenant_id)
        if event_category == "CONTACT":
            logger.info("Syncing contact %s from webhook", resource_id)
            sync_single_contact(sync_service, resource_id)
        elif event_category == "INVOICE":
            logger.info("Syncing invoice %s from webhook", resource_id)
            sync_single_invoice(sync_service, resource_id)
        else:
            logger.warning("Unknown webhook event category: %s", event_category)
    except AlreadyLoggedException:
        raise
    except Exception as exc:
        err = persist_app_error(exc)
        raise AlreadyLoggedException(exc, err.id) from exc


@shared_task(name="apps.workflow.tasks.xero_heartbeat_task")
def xero_heartbeat_task() -> None:
    """Refresh the Xero API token. Beat-scheduled every 5 minutes."""
    scheduler_logger.info("Attempting Xero Heartbeat task.")
    try:
        close_old_connections()
        from apps.workflow.accounting.registry import get_provider

        provider = get_provider()
        result = provider.refresh_token()
        if result:
            scheduler_logger.info("Xero API token refreshed successfully.")
        else:
            scheduler_logger.error("No Xero token available to refresh.")
    except AlreadyLoggedException:
        raise
    except Exception as exc:
        scheduler_logger.error(
            "Error during Xero Heartbeat task: %s", exc, exc_info=True
        )
        app_error = persist_app_error(exc)
        raise AlreadyLoggedException(exc, app_error.id) from exc


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
        _sync_cache.delete(XeroSyncService.SYNC_STATUS_KEY)


@shared_task(name="apps.workflow.tasks.xero_regular_sync_task")
def xero_regular_sync_task() -> None:
    """Beat-scheduled hourly. Dispatches a sync run; the actual sync work
    happens in xero_sync_task whose TaskResult records the true outcome.
    A SUCCESS TaskResult here means "the dispatch decision succeeded" —
    either a sync was kicked off, or one was already running and we
    correctly skipped."""
    scheduler_logger.info("Running Xero Regular Sync task.")
    try:
        close_old_connections()
        task_id, started = XeroSyncService.start_sync()
        if not started:
            scheduler_logger.info(
                "Xero regular sync skipped — sync already in progress (task_id=%s)",
                task_id,
            )
            return
        scheduler_logger.info("Xero regular sync dispatched (task_id=%s)", task_id)
    except AlreadyLoggedException:
        raise
    except Exception as exc:
        scheduler_logger.error(
            "Error during Xero Regular Sync task: %s", exc, exc_info=True
        )
        app_error = persist_app_error(exc)
        raise AlreadyLoggedException(exc, app_error.id) from exc


@shared_task(name="apps.workflow.tasks.xero_30_day_sync_task")
def xero_30_day_sync_task() -> None:
    """Beat-scheduled Saturday 02:00 NZT. Dispatches a sync run; the actual
    sync work happens in xero_sync_task whose TaskResult records the true
    outcome."""
    scheduler_logger.info("Running Xero 30-Day Sync task.")
    try:
        close_old_connections()
        task_id, started = XeroSyncService.start_sync()
        if not started:
            scheduler_logger.info(
                "Xero 30-day sync skipped — sync already in progress (task_id=%s)",
                task_id,
            )
            return
        scheduler_logger.info("Xero 30-day sync dispatched (task_id=%s)", task_id)
    except AlreadyLoggedException:
        raise
    except Exception as exc:
        scheduler_logger.error(
            "Error during Xero 30-Day Sync task: %s", exc, exc_info=True
        )
        app_error = persist_app_error(exc)
        raise AlreadyLoggedException(exc, app_error.id) from exc
