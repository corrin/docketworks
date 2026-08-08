"""Xero webhook handling.

The handler validates the signature, parses the payload, and dispatches each
event to a Celery task — returning 200 immediately. Synchronous in-handler
processing exceeded Xero's 5s redelivery timeout in v1, which triggered
retries that re-enqueued the same events and drained the day quota. Per ADR
0024, anything that calls a third-party API belongs in Celery, not the
request path.

Mounted at the exact-parity URL ``/api/xero/webhook/`` (Xero's portal holds
it) as a plain Django view, allowlisted through the auth-gate middleware —
the HMAC signature IS this endpoint's authentication.
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

from apps.core.errors import persist_app_error
from apps.xero.models import XeroApp
from apps.xero.tasks import process_xero_webhook_event

logger = logging.getLogger(__name__)


def validate_webhook_signature(request: HttpRequest) -> bool:
    """Validate the Xero webhook signature using HMAC-SHA256.

    Xero signs each webhook with the signing key of the Xero app that
    emitted it. During credential rotation an install has two registered
    apps in Xero's portal — each with its own signing key — and both
    apps emit webhooks until the operator deletes the old one. So we
    accept the request if any non-NULL XeroApp.webhook_key produces a
    matching HMAC. If a now-inactive app keeps firing webhooks because
    the operator hasn't deleted it in the Xero portal, that's fine: we
    process them. Cleaning up orphan apps in Xero is the operator's job.

    Raises ``RuntimeError`` (after persisting an AppError) if no XeroApp row
    has a webhook_key set. That state is a deploy-time misconfiguration, not
    a request-time bad-signature event — surfacing it via AppError gets it
    in front of an operator instead of leaving it to rot in log files while
    every webhook silently 401s.
    """
    signature = request.headers.get("x-xero-signature")
    if not signature:
        logger.warning("Missing x-xero-signature header")
        return False

    keys = list(
        XeroApp.objects.exclude(webhook_key__isnull=True).values_list("webhook_key", flat=True)
    )
    if not keys:
        exc = RuntimeError(
            "No XeroApp row has webhook_key set; cannot verify webhook "
            "signatures. Set webhook_key via the Xero Apps admin UI or "
            "the per-install fixture and redeploy."
        )
        persist_app_error(exc)
        raise exc

    body = request.body
    # Compare as bytes: compare_digest on str raises TypeError for non-ASCII
    # input, and this header arrives from the network.
    signature_bytes = signature.encode("utf-8", errors="replace")
    for key in keys:
        if key is None:
            continue  # A XeroApp with no webhook key cannot verify anything.
        expected_signature_bytes = hmac.new(key.encode("utf-8"), body, hashlib.sha256).digest()
        expected_signature = base64.b64encode(expected_signature_bytes)
        if hmac.compare_digest(signature_bytes, expected_signature):
            return True

    return False


@method_decorator(csrf_exempt, name="dispatch")
class XeroWebhookView(View):
    """Accept Xero webhook deliveries and dispatch each event to Celery."""

    def post(  # noqa: C901, PLR0911 -- each branch/return is one distinct webhook contract status
        self, request: HttpRequest
    ) -> HttpResponse:
        """Verify, parse, dispatch; 200/400/401/503 exactly as Xero expects."""
        try:
            valid = validate_webhook_signature(request)
        # deliberate-swallow: the config error is already persisted; a 503
        # tells Xero to RETRY, so the redelivery backlog survives until the
        # operator fixes the key. A raise would 500 and lose that contract;
        # a 4xx would tell Xero to stop trying.
        except RuntimeError as exc:
            # Idempotent — validate_webhook_signature already persisted this,
            # so this returns that same row rather than writing a second.
            err = persist_app_error(exc)
            return HttpResponse(
                f"Service Unavailable: {exc} (error_id={err.id})",
                status=503,
            )
        if not valid:
            return HttpResponse("Unauthorized", status=401)

        try:
            payload = json.loads(request.body.decode("utf-8"))
        # deliberate-swallow: malformed JSON is the sender's error, reshaped
        # to the 400 the webhook contract promises
        except json.JSONDecodeError:
            logger.error("Invalid JSON in webhook payload")
            return HttpResponse("Bad Request", status=400)
        if not isinstance(payload, dict):
            logger.error("Webhook payload is valid JSON but not an object")
            return HttpResponse("Bad Request", status=400)

        # "Intent to receive" validation pings have no events key.
        if "events" not in payload:
            logger.info("Received intent to receive validation")
            return HttpResponse("OK", status=200)

        events = payload.get("events", [])
        if not events:
            logger.warning("Webhook payload contains no events")
            return HttpResponse("OK", status=200)

        if not isinstance(events, list):
            logger.error("Webhook 'events' is not a list")
            return HttpResponse("Bad Request", status=400)

        for event in events:
            if not isinstance(event, dict):
                logger.error("Webhook event is not an object: %r", event)
                continue
            tenant_id = event.get("tenantId")
            if not tenant_id:
                logger.error("Webhook event missing tenantId: %s", event)
                continue
            process_xero_webhook_event.delay(tenant_id, event)

        return HttpResponse("OK", status=200)
