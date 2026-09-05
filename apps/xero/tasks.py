"""Celery tasks for the Xero integration.

Tasks follow ADR 0024: idempotent, tenant-aware (tenant_id is an explicit
argument), write-side (results land in the DB, not in a result backend).
"""

import logging
from typing import Any

from celery import shared_task
from django.db import close_old_connections
from django.db.models import F, Q

from apps.accounting.registry import get_provider, is_accounting_enabled
from apps.core.errors import persist_app_error
from apps.core.models import CompanyDefaults
from apps.purchasing.models import PurchaseOrder
from apps.xero.client import quota_floor_breached
from apps.xero.documents.po import XeroPurchaseOrderManager
from apps.xero.single_sync import sync_single_contact, sync_single_invoice
from apps.xero.sync_service import XeroSyncService

# Re-export so `apps.xero.tasks.xero_sync_task` resolves for beat schedules
# and direct callers. The `@shared_task` decorator runs at import time in the
# worker module, registering the task under this module's name.
from apps.xero.sync_worker import xero_sync_task  # noqa: F401

logger = logging.getLogger(__name__)


class XeroPurchaseOrderPushError(RuntimeError):
    """Xero refused a purchase order push."""


@shared_task(name="apps.xero.tasks.process_xero_webhook_event")
def process_xero_webhook_event(tenant_id: str, event: dict[str, Any]) -> None:
    """Sync a single Xero resource referenced by a webhook event.

    Async on purpose: synchronous in-handler processing exceeded Xero's 5s
    redelivery timeout, triggered retries, and drained the day quota (v1).

    Idempotent: ``sync_single_{contact,invoice}`` use ``update_or_create``
    keyed on the Xero ID, so re-execution converges on the same DB state.
    """
    company_defaults = CompanyDefaults.get_solo()
    # Webhook events never reach the sync engine (they call sync_single_*
    # directly), so this is the gate's only enforcement on this path, not a
    # repeat of the engine's.
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
        # A scheduling decision, not a second copy of the engine's gate: this
        # decides whether to DISPATCH, and the engine decides whether to sync.
        # Dispatching anyway would refresh a token, seed three progress-stream
        # cache keys and post an "aborted" run to the operator's log every
        # hour, forever, on an install that has deliberately turned sync off.
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
        # Same dispatch-level skip as the hourly task, for the same reason.
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


@shared_task(name="apps.xero.tasks.push_purchase_order_to_xero")
def push_purchase_order_to_xero(purchase_order_id: str) -> None:
    """Send a Docketworks-raised purchase order to Xero, creating or updating.

    Xero holds a copy of the order so the supplier's bill has something to
    reconcile against, which only works if the copy is there before the bill
    arrives and stays current afterwards. That is why this is a task and not a
    button: leaving it to an operator makes staying in step someone's job to
    remember, and forgetting it is invisible until the accounts do not match.

    Idempotent (ADR 0024): the manager creates or updates on the order's stored
    ``xero_id``, so a redelivered task converges rather than raising a second
    purchase order at the supplier.
    """
    po = (
        PurchaseOrder.objects.select_related("supplier", "created_by")
        .filter(id=purchase_order_id)
        .first()
    )
    if po is None:
        logger.warning("Purchase order %s vanished before its Xero push", purchase_order_id)
        return
    if po.created_by is None:
        raise ValueError(f"Purchase order {po.po_number} is not Docketworks-owned; refusing push")

    manager = XeroPurchaseOrderManager(purchase_order=po, staff=po.created_by)
    result = manager.sync_to_xero()
    if not result["success"]:
        # Persisted, not swallowed: an order the accounts team cannot see is
        # exactly the failure this push exists to prevent, so it has to surface
        # rather than leave the row quietly out of step (ADR 0019).
        raise XeroPurchaseOrderPushError(
            f"Xero refused purchase order {po.po_number}: {result.get('error')}"
        )
    logger.info("Pushed purchase order %s to Xero (%s)", po.po_number, result.get("xero_id"))


RECONCILE_LIMIT = 50


@shared_task(name="apps.xero.tasks.reconcile_purchase_orders_to_xero")
def reconcile_purchase_orders_to_xero(limit: int = RECONCILE_LIMIT) -> None:
    """Push every Docketworks-raised order whose Xero copy is missing or behind.

    The immediate push queued on write is an optimisation; this is the
    guarantee. Xero refuses work for reasons that have nothing to do with our
    data and everything to do with the moment — the day quota under
    ``xero_automated_day_floor``, a lapsed connection, an outage, a worker that
    died holding the message. Every one of those resolves on its own, and a
    sweep is what turns "resolves on its own" into "the order is in Xero"
    without an operator noticing anything happened.

    That is also why there are no task retries: a retry storms a refusal a later
    sweep handles calmly, and the failure that is NOT transient — an order
    voided in Xero — is prevented instead, because the inbound sync marks it
    deleted and a deleted order is never swept.

    ``xero_last_pushed < updated_at`` is the whole staleness test: the push
    stamps the former and Django stamps the latter, so an edit that has not
    reached Xero is exactly a row where the edit is newer than the send. It
    cannot use ``xero_last_synced`` — every inbound sync writes that one, so a
    pull would report an outstanding send as delivered.
    """
    if quota_floor_breached(CompanyDefaults.get_solo().xero_automated_day_floor):
        # Not an error: the floor exists so automated work yields to
        # interactive use. The next sweep finds the same orders.
        logger.info("Purchase-order reconcile skipped: Xero day quota at floor")
        return

    behind = (
        PurchaseOrder.objects.filter(created_by__isnull=False)
        .exclude(status__in=["draft", "deleted"])
        .filter(Q(xero_last_pushed__isnull=True) | Q(xero_last_pushed__lt=F("updated_at")))
        .order_by("created_at")
        .values_list("id", flat=True)[:limit]
    )
    for po_id in list(behind):
        push_purchase_order_to_xero.delay(str(po_id))
