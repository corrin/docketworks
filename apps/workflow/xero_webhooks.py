"""Xero webhook handling for real-time synchronization."""

import base64
import hashlib
import hmac
import json
import logging
from typing import Any, Dict

from django.conf import settings
from django.core.cache import cache
from django.http import HttpRequest, HttpResponse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from apps.workflow.api.xero.sync import sync_single_contact, sync_single_invoice
from apps.workflow.models import CompanyDefaults
from apps.workflow.services.xero_sync_service import XeroSyncService

logger = logging.getLogger("xero")


def validate_webhook_signature(request: HttpRequest) -> bool:
    """Validate Xero webhook signature using HMAC-SHA256."""
    signature = request.headers.get("x-xero-signature")
    if not signature:
        logger.warning("Missing x-xero-signature header")
        return False

    webhook_key = getattr(settings, "XERO_WEBHOOK_KEY", None)
    if not webhook_key:
        logger.error("XERO_WEBHOOK_KEY not configured in settings")
        return False

    expected_signature_bytes = hmac.new(
        webhook_key.encode("utf-8"), request.body, hashlib.sha256
    ).digest()

    expected_signature = base64.b64encode(expected_signature_bytes).decode("utf-8")

    return hmac.compare_digest(signature, expected_signature)


def process_webhook_event(event: Dict[str, Any]) -> None:
    """Process a single webhook event by syncing the affected resource."""
    event_category = event.get("eventCategory")
    resource_id = event.get("resourceId")
    tenant_id = event.get("tenantId")

    if not all([event_category, resource_id, tenant_id]):
        logger.error(f"Invalid webhook event - missing required fields: {event}")
        return

    # Verify tenant matches our configuration
    company_defaults = CompanyDefaults.get_solo()
    if company_defaults.xero_tenant_id != tenant_id:
        logger.warning(
            f"Webhook event for wrong tenant {tenant_id}, "
            f"expected {company_defaults.xero_tenant_id}"
        )
        return

    # Initialize sync service
    try:
        sync_service = XeroSyncService(tenant_id=company_defaults.xero_tenant_id)
    except Exception as e:
        logger.error(f"Failed to initialize XeroSyncService: {e}")
        return

    if not sync_service.tenant_id:
        logger.error("XeroSyncService has no tenant_id")
        return

    # Process based on category
    if event_category == "CONTACT":
        logger.info(f"Syncing contact {resource_id} from webhook")
        sync_single_contact(sync_service, resource_id)
    elif event_category == "INVOICE":
        logger.info(f"Syncing invoice {resource_id} from webhook")
        sync_single_invoice(sync_service, resource_id)
    else:
        logger.warning(f"Unknown event category: {event_category}")


@method_decorator(csrf_exempt, name="dispatch")
class XeroWebhookView(View):
    """Handle incoming Xero webhook notifications."""

    def post(self, request: HttpRequest) -> HttpResponse:
        """Process incoming webhook payload."""
        if not validate_webhook_signature(request):
            return HttpResponse("Unauthorized", status=401)

        try:
            payload = json.loads(request.body.decode("utf-8"))
        except json.JSONDecodeError:
            logger.error("Invalid JSON in webhook payload")
            return HttpResponse("Bad Request", status=400)

        # Handle "Intent to receive" validation
        if "events" not in payload:
            logger.info("Received intent to receive validation")
            return HttpResponse("OK", status=200)

        events = payload.get("events", [])
        if not events:
            logger.warning("Webhook payload contains no events")
            return HttpResponse("OK", status=200)

        # Queue events for async processing
        queue_key = "xero_webhook_queue"
        queue = cache.get(queue_key, [])

        for event in events:
            event["queued_at"] = timezone.now().isoformat()
            queue.append(event)

        cache.set(queue_key, queue, 3600)  # 1 hour expiry

        # Process queue if not already processing
        lock_key = "xero_webhook_processing_lock"
        if cache.add(lock_key, True, 60):  # 60 second lock
            try:
                process_webhook_queue()
            finally:
                cache.delete(lock_key)

        return HttpResponse("OK", status=200)


def process_webhook_queue() -> None:
    """Process all queued webhook events."""
    queue_key = "xero_webhook_queue"
    queue = cache.get(queue_key, [])

    if not queue:
        return

    # Clear queue before processing to avoid reprocessing
    cache.delete(queue_key)

    for event in queue:
        try:
            process_webhook_event(event)
        except Exception as e:
            logger.exception(
                f"Error processing webhook event {event.get('resourceId')}: {e}"
            )
