"""Xero webhook handling.

The handler validates the signature, parses the payload, and dispatches each
event to a Celery task — returning 200 immediately. Synchronous in-handler
processing exceeded Xero's 5s redelivery timeout, which triggered retries
that re-enqueued the same events and drained the day quota (Trello #291).
Per ADR 0024, anything that calls a third-party API belongs in Celery, not
the request path.
"""

import base64
import hashlib
import hmac
import json
import logging

from django.http import HttpRequest, HttpResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from apps.workflow.models import XeroApp
from apps.workflow.tasks import process_xero_webhook_event

logger = logging.getLogger("xero")


def validate_webhook_signature(request: HttpRequest) -> bool:
    """Validate Xero webhook signature using HMAC-SHA256.

    Xero signs each webhook with the signing key of the Xero app that
    emitted it. During credential rotation an install has two registered
    apps in Xero's portal — each with its own signing key — and both
    apps emit webhooks until the operator deletes the old one. So we
    accept the request if any non-blank XeroApp.webhook_key produces a
    matching HMAC. If a now-inactive app keeps firing webhooks because
    the operator hasn't deleted it in the Xero portal, that's fine: we
    process them. Cleaning up orphan apps in Xero is the operator's job.
    """
    signature = request.headers.get("x-xero-signature")
    if not signature:
        logger.warning("Missing x-xero-signature header")
        return False

    keys = list(
        XeroApp.objects.exclude(webhook_key="").values_list("webhook_key", flat=True)
    )
    if not keys:
        logger.error(
            "No XeroApp row has webhook_key set; cannot verify webhook signatures"
        )
        return False

    body = request.body
    for key in keys:
        expected_signature_bytes = hmac.new(
            key.encode("utf-8"), body, hashlib.sha256
        ).digest()
        expected_signature = base64.b64encode(expected_signature_bytes).decode("utf-8")
        if hmac.compare_digest(signature, expected_signature):
            return True

    return False


@method_decorator(csrf_exempt, name="dispatch")
class XeroWebhookView(View):
    """Accept Xero webhook deliveries and dispatch each event to Celery."""

    def post(self, request: HttpRequest) -> HttpResponse:
        if not validate_webhook_signature(request):
            return HttpResponse("Unauthorized", status=401)

        try:
            payload = json.loads(request.body.decode("utf-8"))
        except json.JSONDecodeError:
            logger.error("Invalid JSON in webhook payload")
            return HttpResponse("Bad Request", status=400)

        # "Intent to receive" validation pings have no events key.
        if "events" not in payload:
            logger.info("Received intent to receive validation")
            return HttpResponse("OK", status=200)

        events = payload.get("events", [])
        if not events:
            logger.warning("Webhook payload contains no events")
            return HttpResponse("OK", status=200)

        for event in events:
            tenant_id = event.get("tenantId")
            if not tenant_id:
                logger.error("Webhook event missing tenantId: %s", event)
                continue
            process_xero_webhook_event.delay(tenant_id, event)

        return HttpResponse("OK", status=200)
