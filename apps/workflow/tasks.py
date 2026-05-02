"""Celery tasks for the workflow app.

Tasks here follow ADR 0024: idempotent, tenant-aware (tenant_id is an
explicit argument), write-side (results land in the DB, not in a result
backend). `.delay().get()` is forbidden.
"""

import logging
from typing import Any, Dict

from celery import shared_task
from django.conf import settings

from apps.workflow.api.xero.client import quota_floor_breached
from apps.workflow.api.xero.sync import sync_single_contact, sync_single_invoice
from apps.workflow.exceptions import AlreadyLoggedException
from apps.workflow.models import CompanyDefaults
from apps.workflow.services.error_persistence import persist_app_error
from apps.workflow.services.xero_sync_service import XeroSyncService

logger = logging.getLogger("xero")

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
