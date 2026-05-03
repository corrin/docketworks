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

from apps.workflow.exceptions import AlreadyLoggedException
from apps.workflow.models import XeroApp
from apps.workflow.services.error_persistence import persist_app_error
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

    Raises ``AlreadyLoggedException`` (after persisting an AppError) if
    no XeroApp row has a webhook_key set. That state is a deploy-time
    misconfiguration, not a request-time bad-signature event — surfacing
    it via AppError gets it in front of an operator instead of leaving
    it to rot in log files while every webhook silently 401s.
    """
    signature = request.headers.get("x-xero-signature")
    if not signature:
        logger.warning("Missing x-xero-signature header")
        return False

    keys = list(
        XeroApp.objects.exclude(webhook_key="").values_list("webhook_key", flat=True)
    )
    if not keys:
        exc = RuntimeError(
            "No XeroApp row has webhook_key set; cannot verify webhook "
            "signatures. Set webhook_key via the Xero Apps admin UI or "
            "the per-install fixture and redeploy."
        )
        err = persist_app_error(exc)
        raise AlreadyLoggedException(exc, err.id) from exc

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
        try:
            valid = validate_webhook_signature(request)
        except AlreadyLoggedException as exc:
            # Config error already persisted as AppError. Return 503 so
            # Xero treats this as a transient failure and retries — by
            # the time the operator notices and fixes the config, the
            # backlog of redelivered events still gets processed. A 4xx
            # would tell Xero "stop trying", which is the wrong signal
            # for a fixable config bug.
            return HttpResponse(
                f"Service Unavailable: {exc} (error_id={exc.app_error_id})",
                status=503,
            )
        if not valid:
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
