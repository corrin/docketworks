"""The Xero webhook surface: signature auth, dispatch, and the processing task.

Business risks: the handler must return 200 quickly (well under Xero's 5s
redelivery timeout) and hand each event to Celery — synchronous in-handler
processing caused the 2026-05-01 day-quota exhaustion. The HMAC signature is
this endpoint's ONLY authentication (the URL is anonymous by allowlist), so a
verification hole means anyone can inject fake invoice/contact updates, and a
verification that is too strict during credential rotation silently drops real
Xero deliveries.
"""

import base64
import hashlib
import hmac
import json
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from django.test import Client, override_settings

if TYPE_CHECKING:
    from django.test.client import _MonkeyPatchedWSGIResponse

from apps.core.middleware import AUTH_ANON_ALLOWLIST_EXACT
from apps.core.models import AppError, CompanyDefaults
from apps.xero.tasks import process_xero_webhook_event

from .conftest import make_xero_app

pytestmark = pytest.mark.django_db

WEBHOOK_URL = "/api/xero/webhook/"
WEBHOOK_KEY = "unit-test-webhook-key"
TENANT_ID = "tenant-abc-123"


def _sign(body: bytes, key: str = WEBHOOK_KEY) -> str:
    digest = hmac.new(key.encode("utf-8"), body, hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


def _event(
    *,
    category: str = "INVOICE",
    resource_id: str = "inv-1",
    tenant_id: str = TENANT_ID,
    event_id: str = "evt-1",
) -> dict[str, str]:
    return {
        "eventCategory": category,
        "resourceId": resource_id,
        "tenantId": tenant_id,
        "eventId": event_id,
        "eventType": "UPDATE",
        "eventDateUtc": "2026-05-02T00:00:00",
    }


def _post(
    client: Client, body: bytes, *, signature: str | None = None
) -> "_MonkeyPatchedWSGIResponse":
    """POST the raw body with an X-Xero-Signature header (default: a valid one)."""
    return client.post(
        WEBHOOK_URL,
        data=body,
        content_type="application/json",
        headers={"x-xero-signature": signature if signature is not None else _sign(body)},
    )


class TestWebhookHandler:
    """The HTTP layer: verify, parse, dispatch, return fast."""

    @pytest.fixture(autouse=True)
    def _app_row(self) -> None:
        make_xero_app(webhook_key=WEBHOOK_KEY)

    def test_valid_signature_from_anonymous_request_returns_200(self, client: Client) -> None:
        """The signature IS the auth — no cookie, no session, still 200.

        DEBUG=False so the auth-gate middleware actually runs; in DEBUG it
        waves everything through and the test would prove nothing.
        """
        body = json.dumps({"events": [_event()]}).encode("utf-8")
        with (
            override_settings(DEBUG=False),
            patch.object(process_xero_webhook_event, "delay") as mock_delay,
        ):
            response = _post(client, body)
        assert response.status_code == 200
        mock_delay.assert_called_once()

    def test_webhook_path_is_on_the_anonymous_allowlist(self) -> None:
        """Xero holds this URL and sends no cookie; dropping the allowlist
        entry would 401 every delivery in production."""
        assert WEBHOOK_URL in AUTH_ANON_ALLOWLIST_EXACT

    def test_invalid_signature_returns_401_and_does_not_dispatch(self, client: Client) -> None:
        body = json.dumps({"events": [_event()]}).encode("utf-8")
        with patch.object(process_xero_webhook_event, "delay") as mock_delay:
            response = _post(client, body, signature="not-a-valid-signature")
        assert response.status_code == 401
        mock_delay.assert_not_called()

    def test_missing_signature_header_returns_401(self, client: Client) -> None:
        body = json.dumps({"events": [_event()]}).encode("utf-8")
        with patch.object(process_xero_webhook_event, "delay") as mock_delay:
            response = client.post(WEBHOOK_URL, data=body, content_type="application/json")
        assert response.status_code == 401
        mock_delay.assert_not_called()

    def test_invalid_json_body_returns_400(self, client: Client) -> None:
        body = b"not json {"
        with patch.object(process_xero_webhook_event, "delay") as mock_delay:
            response = _post(client, body)
        assert response.status_code == 400
        mock_delay.assert_not_called()

    def test_intent_to_receive_returns_200_without_dispatch(self, client: Client) -> None:
        """Xero's subscription handshake has no events key and must get a 200,
        or the webhook can never be registered at all."""
        body = json.dumps({}).encode("utf-8")
        with patch.object(process_xero_webhook_event, "delay") as mock_delay:
            response = _post(client, body)
        assert response.status_code == 200
        mock_delay.assert_not_called()

    def test_empty_events_list_returns_200_without_dispatch(self, client: Client) -> None:
        body = json.dumps({"events": []}).encode("utf-8")
        with patch.object(process_xero_webhook_event, "delay") as mock_delay:
            response = _post(client, body)
        assert response.status_code == 200
        mock_delay.assert_not_called()

    def test_each_event_is_dispatched_to_celery_with_tenant_arg(self, client: Client) -> None:
        events = [
            _event(category="INVOICE", resource_id="inv-1", event_id="e1"),
            _event(category="CONTACT", resource_id="con-2", event_id="e2"),
        ]
        body = json.dumps({"events": events}).encode("utf-8")
        with patch.object(process_xero_webhook_event, "delay") as mock_delay:
            response = _post(client, body)
        assert response.status_code == 200
        assert mock_delay.call_count == 2
        # tenant_id rides first, positionally; the event payload second.
        for call, expected in zip(mock_delay.call_args_list, events, strict=True):
            args, _kwargs = call
            assert args[0] == TENANT_ID
            assert args[1] == expected

    def test_event_without_tenant_id_is_skipped(self, client: Client) -> None:
        """One malformed event must not poison the batch — Xero would redeliver
        the whole payload and the well-formed events with it."""
        bad = _event()
        bad.pop("tenantId")
        good = _event(resource_id="inv-2", event_id="e2")
        body = json.dumps({"events": [bad, good]}).encode("utf-8")
        with patch.object(process_xero_webhook_event, "delay") as mock_delay:
            response = _post(client, body)
        assert response.status_code == 200
        assert mock_delay.call_count == 1
        args, _kwargs = mock_delay.call_args
        assert args[1]["resourceId"] == "inv-2"


class TestWebhookKeyRotation:
    """Multi-key acceptance during a Xero credential rotation.

    During a rotation an install has TWO XeroApp rows registered with Xero
    (the old app being phased out and its replacement), each with its own
    webhook signing key, and both apps emit signed webhooks until the operator
    deletes the old one in Xero's portal. Rejecting the old key drops real
    deliveries mid-rotation; accepting arbitrary keys forges them.
    """

    def test_signature_from_inactive_row_is_accepted(self, client: Client) -> None:
        make_xero_app(label="Old", client_id="c-old", webhook_key="key-old", is_active=False)
        make_xero_app(label="New", client_id="c-new", webhook_key="key-new", is_active=True)

        body = json.dumps({"events": [_event()]}).encode("utf-8")
        for key in ("key-old", "key-new"):
            with patch.object(process_xero_webhook_event, "delay") as mock_delay:
                response = _post(client, body, signature=_sign(body, key=key))
            assert response.status_code == 200, f"signature with {key!r} must be accepted"
            mock_delay.assert_called_once()

    def test_unknown_key_is_rejected_even_with_multiple_keys(self, client: Client) -> None:
        """The multi-key loop is any-of, not anything-goes."""
        make_xero_app(label="A", client_id="c-a", webhook_key="key-a")
        make_xero_app(label="B", client_id="c-b", webhook_key="key-b")

        body = json.dumps({"events": [_event()]}).encode("utf-8")
        with patch.object(process_xero_webhook_event, "delay") as mock_delay:
            response = _post(client, body, signature=_sign(body, key="not-on-any-row"))
        assert response.status_code == 401
        mock_delay.assert_not_called()


class TestWebhookNoKeyConfigured:
    """Zero webhook keys → loud 503, not an endless silent 401.

    A deployment whose XeroApp rows all lack a webhook_key used to 401 every
    delivery indefinitely with only a log line to show for it. The 503 makes
    Xero retry (so the backlog survives until the key is fixed) and the
    persisted AppError puts the misconfiguration in front of an operator.
    """

    def test_no_rows_returns_503_and_persists_app_error(self, client: Client) -> None:
        body = json.dumps({"events": [_event()]}).encode("utf-8")
        with patch.object(process_xero_webhook_event, "delay") as mock_delay:
            response = _post(client, body)
        assert response.status_code == 503
        app_error = AppError.objects.get()
        assert "webhook_key" in app_error.message
        # The body carries the error id so the operator can look it up.
        assert str(app_error.id).encode() in response.content
        mock_delay.assert_not_called()

    def test_rows_without_keys_still_return_503_with_one_app_error(self, client: Client) -> None:
        make_xero_app(label="Blank", client_id="c-blank", webhook_key=None)
        body = json.dumps({"events": [_event()]}).encode("utf-8")
        response = _post(client, body)
        assert response.status_code == 503
        # One failure, one row (ADR 0001) — even though the view's handler
        # persists again after validate_webhook_signature already did.
        assert AppError.objects.count() == 1


def _configure_defaults(
    *, tenant_id: str | None = TENANT_ID, enable_xero_sync: bool = True
) -> None:
    defaults = CompanyDefaults.get_solo()
    defaults.xero_tenant_id = tenant_id
    defaults.enable_xero_sync = enable_xero_sync
    defaults.save(update_fields=["xero_tenant_id", "enable_xero_sync"])


class TestProcessXeroWebhookEventTask:
    """The Celery task: gates first, then route by category, fail loudly.

    Business risks: syncing another tenant's data into this install, burning
    the reserved user quota on automated webhook traffic, and sync failures
    vanishing without an AppError.
    """

    def test_invoice_event_syncs_that_invoice(self) -> None:
        _configure_defaults()
        with (
            patch("apps.xero.tasks.quota_floor_breached", return_value=False),
            patch("apps.xero.tasks.sync_single_invoice") as mock_invoice,
            patch("apps.xero.tasks.sync_single_contact") as mock_contact,
        ):
            process_xero_webhook_event(TENANT_ID, _event(category="INVOICE", resource_id="inv-9"))
        mock_invoice.assert_called_once_with(TENANT_ID, "inv-9")
        mock_contact.assert_not_called()

    def test_contact_event_syncs_that_contact(self) -> None:
        _configure_defaults()
        with (
            patch("apps.xero.tasks.quota_floor_breached", return_value=False),
            patch("apps.xero.tasks.sync_single_invoice") as mock_invoice,
            patch("apps.xero.tasks.sync_single_contact") as mock_contact,
        ):
            process_xero_webhook_event(TENANT_ID, _event(category="CONTACT", resource_id="con-9"))
        mock_contact.assert_called_once_with(TENANT_ID, "con-9")
        mock_invoice.assert_not_called()

    def test_disabled_sync_gate_skips_before_quota_or_sync(self) -> None:
        """enable_xero_sync=False must stop everything — including the quota
        probe, which itself costs nothing but marks the gate as leaky."""
        _configure_defaults(enable_xero_sync=False)
        with (
            patch("apps.xero.tasks.quota_floor_breached") as mock_quota,
            patch("apps.xero.tasks.sync_single_invoice") as mock_invoice,
            patch("apps.xero.tasks.sync_single_contact") as mock_contact,
        ):
            process_xero_webhook_event(TENANT_ID, _event())
        mock_quota.assert_not_called()
        mock_invoice.assert_not_called()
        mock_contact.assert_not_called()

    def test_quota_floor_returns_without_raising_or_syncing(self) -> None:
        """At the floor the task must RETURN — raising would make Celery retry
        and the retries would drain the very quota the floor reserves."""
        _configure_defaults()
        with (
            patch("apps.xero.tasks.quota_floor_breached", return_value=True),
            patch("apps.xero.tasks.sync_single_invoice") as mock_invoice,
            patch("apps.xero.tasks.sync_single_contact") as mock_contact,
        ):
            process_xero_webhook_event(TENANT_ID, _event())
        mock_invoice.assert_not_called()
        mock_contact.assert_not_called()

    def test_wrong_tenant_skips_sync(self) -> None:
        """An event for a tenant this install is not bound to must never write
        that tenant's data into this database."""
        _configure_defaults(tenant_id="some-other-tenant")
        with (
            patch("apps.xero.tasks.quota_floor_breached", return_value=False),
            patch("apps.xero.tasks.sync_single_invoice") as mock_invoice,
            patch("apps.xero.tasks.sync_single_contact") as mock_contact,
        ):
            process_xero_webhook_event(TENANT_ID, _event())
        mock_invoice.assert_not_called()
        mock_contact.assert_not_called()

    def test_unknown_event_category_does_not_sync_or_raise(self) -> None:
        """Xero adding a new category must degrade to a logged skip, not a
        retry loop."""
        _configure_defaults()
        with (
            patch("apps.xero.tasks.quota_floor_breached", return_value=False),
            patch("apps.xero.tasks.sync_single_invoice") as mock_invoice,
            patch("apps.xero.tasks.sync_single_contact") as mock_contact,
        ):
            process_xero_webhook_event(TENANT_ID, _event(category="UNHANDLED_THING"))
        mock_invoice.assert_not_called()
        mock_contact.assert_not_called()

    def test_event_missing_required_fields_skips_without_raising(self) -> None:
        _configure_defaults()
        with (
            patch("apps.xero.tasks.quota_floor_breached", return_value=False),
            patch("apps.xero.tasks.sync_single_invoice") as mock_invoice,
            patch("apps.xero.tasks.sync_single_contact") as mock_contact,
        ):
            process_xero_webhook_event(TENANT_ID, {"eventId": "x"})
        mock_invoice.assert_not_called()
        mock_contact.assert_not_called()

    def test_sync_failure_persists_app_error_and_reraises(self) -> None:
        """A failed sync must leave a row an operator can find, and re-raise
        so Celery records the failure instead of a phantom SUCCESS."""
        _configure_defaults()
        before = AppError.objects.count()
        with (
            patch("apps.xero.tasks.quota_floor_breached", return_value=False),
            patch(
                "apps.xero.tasks.sync_single_invoice",
                side_effect=RuntimeError("xero blew up"),
            ),
            pytest.raises(RuntimeError),
        ):
            process_xero_webhook_event(TENANT_ID, _event())
        assert AppError.objects.count() == before + 1
