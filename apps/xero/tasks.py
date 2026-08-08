"""Celery tasks for the Xero integration.

Tasks follow ADR 0024: idempotent, tenant-aware (tenant_id is an explicit
argument), write-side (results land in the DB, not in a result backend).
"""

import logging
from typing import Any

from celery import shared_task
from django.db import close_old_connections

from apps.accounting.registry import get_provider, is_accounting_enabled
from apps.core.errors import persist_app_error
from apps.core.models import CompanyDefaults
from apps.xero.client import quota_floor_breached
from apps.xero.single_sync import sync_single_contact, sync_single_invoice
from apps.xero.sync_service import XeroSyncService

# Re-export so `apps.xero.tasks.xero_sync_task` resolves for beat schedules
# and direct callers. The `@shared_task` decorator runs at import time in the
# worker module, registering the task under this module's name.
from apps.xero.sync_worker import xero_sync_task  # noqa: F401

logger = logging.getLogger(__name__)


@shared_task(name="apps.xero.tasks.process_xero_webhook_event")
def process_xero_webhook_event(tenant_id: str, event: dict[str, Any]) -> None:
    """Sync a single Xero resource referenced by a webhook event.

    Async on purpose: synchronous in-handler processing exceeded Xero's 5s
    redelivery timeout, triggered retries, and drained the day quota (v1).

    Idempotent: ``sync_single_{contact,invoice}`` use ``update_or_create``
    keyed on the Xero ID, so re-execution converges on the same DB state.
    """
    company_defaults = CompanyDefaults.get_solo()
    if not company_defaults.enable_xero_sync:
        return

    if quota_floor_breached(company_defaults.xero_automated_day_floor):
        logger.warning(
            "Xero day quota at floor (%s) — skipping webhook event %s",
            company_defaults.xero_automated_day_floor,
            event,
        )
        # Return (do not raise) — raising would make Celery retry indefinitely.
        return

    event_category = event.get("eventCategory")
    resource_id = event.get("resourceId")

    if not event_category or not resource_id:
        logger.error("Invalid webhook event - missing required fields: %s", event)
        return

    if company_defaults.xero_tenant_id != tenant_id:
        logger.warning(
            "Webhook event for wrong tenant %s, expected %s",
            tenant_id,
            company_defaults.xero_tenant_id,
        )
        return

    try:
        if event_category == "CONTACT":
            logger.info("Syncing contact %s from webhook", resource_id)
            sync_single_contact(tenant_id, resource_id)
        elif event_category == "INVOICE":
            logger.info("Syncing invoice %s from webhook", resource_id)
            sync_single_invoice(tenant_id, resource_id)
        else:
            logger.warning("Unknown webhook event category: %s", event_category)
    except Exception as exc:
        persist_app_error(exc)
        raise


@shared_task(name="apps.xero.tasks.xero_heartbeat_task")
def xero_heartbeat_task() -> None:
    """Refresh the Xero API token. Beat-scheduled every 5 minutes."""
    logger.info("Attempting Xero Heartbeat task.")
    try:
        close_old_connections()
        provider = get_provider()
        result = provider.get_valid_token()
        if result:
            logger.info("Xero token valid (refreshed if it was near expiry).")
        else:
            logger.error("No Xero token available to refresh.")
    except Exception as exc:
        logger.exception("Error during Xero Heartbeat task")
        persist_app_error(exc)
        raise


@shared_task(name="apps.xero.tasks.xero_regular_sync_task")
def xero_regular_sync_task() -> None:
    """Dispatch the hourly sync run.

    A SUCCESS TaskResult here means "the dispatch decision succeeded" —
    either a sync was kicked off, or one was already running / the token
    was invalid and we correctly skipped. The actual sync work happens in
    xero_sync_task, whose TaskResult records the true outcome.
    """
    logger.info("Running Xero Regular Sync task.")
    try:
        close_old_connections()
        if not is_accounting_enabled():
            logger.info("Xero regular sync skipped: enable_xero_sync is False")
            return
        result = XeroSyncService.start_sync()
        if result.reason == "already_running":
            logger.info(
                "Xero regular sync skipped — sync already in progress (task_id=%s)",
                result.task_id,
            )
            return
        if result.reason == "no_valid_token":
            logger.error("Xero regular sync skipped: no valid Xero token")
            return

        logger.info("Xero regular sync dispatched (task_id=%s)", result.task_id)
    except Exception as exc:
        logger.exception("Error during Xero Regular Sync task")
        persist_app_error(exc)
        raise


@shared_task(name="apps.xero.tasks.xero_30_day_sync_task")
def xero_30_day_sync_task() -> None:
    """Dispatch the weekly deep-sync opportunity (Saturday 02:00 NZT).

    The 30/90-day deep-sync decision lives inside ``synchronise_xero_data``;
    this task, like the hourly one, only dispatches a run.
    """
    logger.info("Running Xero 30-day Sync task.")
    try:
        close_old_connections()
        if not is_accounting_enabled():
            logger.info("Xero 30-day sync skipped: enable_xero_sync is False")
            return
        result = XeroSyncService.start_sync()
        logger.info(
            "Xero 30-day sync dispatch result: %s (task_id=%s)", result.reason, result.task_id
        )
    except Exception as exc:
        logger.exception("Error during Xero 30-day Sync task")
        persist_app_error(exc)
        raise
