"""Tests for the Xero webhook handler and its Celery task.

The handler must return 200 quickly (well under Xero's 5s redelivery timeout)
and dispatch each event to a Celery task — synchronous processing inside the
POST handler caused the 2026-05-01 day-quota exhaustion (Trello card #291).
"""

import base64
import hashlib
import hmac
import json
import socket
import time
import unittest
from unittest.mock import patch

import pytest
import redis
from django.test import RequestFactory, TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from apps.workflow.exceptions import AlreadyLoggedException
from apps.workflow.tasks import process_xero_webhook_event
from apps.workflow.xero_webhooks import XeroWebhookView
from docketworks.celery import app as celery_app

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
):
    return {
        "eventCategory": category,
        "resourceId": resource_id,
        "tenantId": tenant_id,
        "eventId": event_id,
        "eventType": "UPDATE",
        "eventDateUtc": "2026-05-02T00:00:00",
    }


@override_settings(XERO_WEBHOOK_KEY=WEBHOOK_KEY)
class XeroWebhookHandlerTests(TestCase):
    """The HTTP layer — must return 200 fast and dispatch via Celery."""

    def setUp(self) -> None:
        self.factory = RequestFactory()
        self.url = reverse("xero_webhook")

    def _post(self, body_bytes: bytes, *, signature: str | None = None):
        request = self.factory.post(
            self.url,
            data=body_bytes,
            content_type="application/json",
            HTTP_X_XERO_SIGNATURE=(
                signature if signature is not None else _sign(body_bytes)
            ),
        )
        return XeroWebhookView.as_view()(request)

    def test_invalid_signature_returns_401_and_does_not_dispatch(self) -> None:
        body = json.dumps({"events": [_event()]}).encode("utf-8")
        with patch.object(process_xero_webhook_event, "delay") as mock_delay:
            response = self._post(body, signature="not-a-valid-signature")
        self.assertEqual(response.status_code, 401)
        mock_delay.assert_not_called()

    def test_missing_signature_returns_401(self) -> None:
        body = json.dumps({"events": [_event()]}).encode("utf-8")
        request = self.factory.post(
            self.url, data=body, content_type="application/json"
        )
        response = XeroWebhookView.as_view()(request)
        self.assertEqual(response.status_code, 401)

    def test_invalid_json_body_returns_400(self) -> None:
        body = b"not json {"
        with patch.object(process_xero_webhook_event, "delay") as mock_delay:
            response = self._post(body)
        self.assertEqual(response.status_code, 400)
        mock_delay.assert_not_called()

    def test_intent_to_receive_returns_200_without_dispatch(self) -> None:
        body = json.dumps({}).encode("utf-8")
        with patch.object(process_xero_webhook_event, "delay") as mock_delay:
            response = self._post(body)
        self.assertEqual(response.status_code, 200)
        mock_delay.assert_not_called()

    def test_empty_events_list_returns_200_without_dispatch(self) -> None:
        body = json.dumps({"events": []}).encode("utf-8")
        with patch.object(process_xero_webhook_event, "delay") as mock_delay:
            response = self._post(body)
        self.assertEqual(response.status_code, 200)
        mock_delay.assert_not_called()

    def test_each_event_is_dispatched_to_celery_with_tenant_arg(self) -> None:
        events = [
            _event(category="INVOICE", resource_id="inv-1", event_id="e1"),
            _event(category="CONTACT", resource_id="con-2", event_id="e2"),
        ]
        body = json.dumps({"events": events}).encode("utf-8")
        with patch.object(process_xero_webhook_event, "delay") as mock_delay:
            response = self._post(body)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(mock_delay.call_count, 2)
        # tenant_id is passed positionally as the first argument; event payload second.
        for call, expected in zip(mock_delay.call_args_list, events):
            args, _kwargs = call
            self.assertEqual(args[0], TENANT_ID)
            self.assertEqual(args[1], expected)

    def test_event_without_tenant_id_is_skipped(self) -> None:
        bad = _event()
        bad.pop("tenantId")
        good = _event(resource_id="inv-2", event_id="e2")
        body = json.dumps({"events": [bad, good]}).encode("utf-8")
        with patch.object(process_xero_webhook_event, "delay") as mock_delay:
            response = self._post(body)
        self.assertEqual(response.status_code, 200)
        # Only the well-formed event dispatches.
        self.assertEqual(mock_delay.call_count, 1)
        args, _ = mock_delay.call_args
        self.assertEqual(args[1]["resourceId"], "inv-2")


class ProcessXeroWebhookEventTaskTests(TestCase):
    """The Celery task body — runs synchronously in tests via eager mode."""

    def _patch_company_defaults(self, configured_tenant_id: str = TENANT_ID):
        from types import SimpleNamespace

        return patch(
            "apps.workflow.tasks.CompanyDefaults.get_solo",
            return_value=SimpleNamespace(xero_tenant_id=configured_tenant_id),
        )

    def _patch_sync_service(self):
        return patch(
            "apps.workflow.tasks.XeroSyncService",
            autospec=True,
        )

    def test_invoice_event_calls_sync_single_invoice(self) -> None:
        with (
            self._patch_company_defaults(),
            self._patch_sync_service() as mock_svc,
            patch("apps.workflow.tasks.sync_single_invoice") as mock_invoice,
            patch("apps.workflow.tasks.sync_single_contact") as mock_contact,
        ):
            process_xero_webhook_event(TENANT_ID, _event(category="INVOICE"))
        mock_invoice.assert_called_once()
        mock_contact.assert_not_called()
        # XeroSyncService is constructed with the explicit tenant_id arg.
        mock_svc.assert_called_once_with(tenant_id=TENANT_ID)

    def test_contact_event_calls_sync_single_contact(self) -> None:
        with (
            self._patch_company_defaults(),
            self._patch_sync_service(),
            patch("apps.workflow.tasks.sync_single_invoice") as mock_invoice,
            patch("apps.workflow.tasks.sync_single_contact") as mock_contact,
        ):
            process_xero_webhook_event(
                TENANT_ID, _event(category="CONTACT", resource_id="con-1")
            )
        mock_contact.assert_called_once()
        mock_invoice.assert_not_called()

    def test_wrong_tenant_skips_sync(self) -> None:
        with (
            self._patch_company_defaults(configured_tenant_id="some-other-tenant"),
            self._patch_sync_service() as mock_svc,
            patch("apps.workflow.tasks.sync_single_invoice") as mock_invoice,
            patch("apps.workflow.tasks.sync_single_contact") as mock_contact,
        ):
            process_xero_webhook_event(TENANT_ID, _event())
        mock_svc.assert_not_called()
        mock_invoice.assert_not_called()
        mock_contact.assert_not_called()

    def test_unknown_event_category_does_not_dispatch(self) -> None:
        with (
            self._patch_company_defaults(),
            self._patch_sync_service(),
            patch("apps.workflow.tasks.sync_single_invoice") as mock_invoice,
            patch("apps.workflow.tasks.sync_single_contact") as mock_contact,
        ):
            process_xero_webhook_event(TENANT_ID, _event(category="UNHANDLED_THING"))
        mock_invoice.assert_not_called()
        mock_contact.assert_not_called()

    def test_missing_required_fields_skips_without_raising(self) -> None:
        bad_event = {"eventId": "x"}  # no category / resourceId / tenantId
        with self._patch_company_defaults(), self._patch_sync_service() as mock_svc:
            # Should not raise, should not even build a sync service.
            process_xero_webhook_event(TENANT_ID, bad_event)
        mock_svc.assert_not_called()

    def test_sync_exception_persists_and_raises_already_logged(self) -> None:
        from apps.workflow.models import AppError

        before = AppError.objects.count()

        def boom(*args, **kwargs):
            raise RuntimeError("xero blew up")

        with (
            self._patch_company_defaults(),
            self._patch_sync_service(),
            patch("apps.workflow.tasks.sync_single_invoice", side_effect=boom),
        ):
            with self.assertRaises(AlreadyLoggedException):
                process_xero_webhook_event(TENANT_ID, _event())

        after = AppError.objects.count()
        self.assertEqual(after, before + 1)

    def test_task_is_idempotent_under_redelivery(self) -> None:
        """ADR 0024 rule: a task running twice must be safe.

        Our task body has no local state — it delegates to sync_single_*,
        which use update_or_create on the Xero ID, so re-execution converges
        on the same DB state. This test locks in that the *task itself* is
        deterministic across redeliveries: same args in, same calls out, no
        crashes, no leaked side effects.
        """
        with (
            self._patch_company_defaults(),
            self._patch_sync_service() as mock_svc,
            patch("apps.workflow.tasks.sync_single_invoice") as mock_invoice,
        ):
            event = _event()
            process_xero_webhook_event(TENANT_ID, event)
            process_xero_webhook_event(TENANT_ID, event)

        self.assertEqual(mock_invoice.call_count, 2)
        self.assertEqual(mock_svc.call_count, 2)
        # Both deliveries call the sync function with identical positional args
        # — no hidden state in the task body that would shift behaviour run-to-run.
        self.assertEqual(
            mock_invoice.call_args_list[0],
            mock_invoice.call_args_list[1],
        )


TEST_BROKER_DB = 15  # unused by dev/UAT/prod — db 0 is channels, db 1 is celery
TEST_BROKER_URL = f"redis://127.0.0.1:6379/{TEST_BROKER_DB}"


def _redis_reachable() -> bool:
    """Cheap TCP probe — Django's `manage.py test` ignores pytest markers, so
    these tests run regardless. We self-skip if Redis isn't running so a dev
    without Redis (or CI without the service) gets a skip, not a connection
    error."""
    try:
        with socket.create_connection(("127.0.0.1", 6379), timeout=0.5):
            return True
    except OSError:
        return False


@pytest.mark.broker
@unittest.skipUnless(
    _redis_reachable(),
    "Redis not reachable on 127.0.0.1:6379 — broker integration tests skipped",
)
@override_settings(
    XERO_WEBHOOK_KEY=WEBHOOK_KEY,
    CELERY_TASK_ALWAYS_EAGER=False,
    CELERY_TASK_EAGER_PROPAGATES=False,
    CELERY_BROKER_URL=TEST_BROKER_URL,
)
class BrokerRoundtripTests(TransactionTestCase):
    """Real Redis broker — opt-in via `pytest -m broker`.

    Why this exists: the unit tests run in eager mode, which (a) skips JSON
    serialization through the broker and (b) makes the handler trivially
    fast regardless of what the task does. Both blind spots correspond to
    real failure modes — the 2026-05-01 incident was caused by the handler
    blocking on inline work, exactly what eager mode hides.

    What it does:
    - Flips eager mode off so `.delay()` actually pushes through Redis.
    - Points at an unused Redis db (15) so we can't accidentally inject a
      task into dev's celery queue.
    - Verifies the handler returns sub-500ms — the property that broke
      the original feedback loop.
    - Verifies the message lands in the broker (proves serialization).

    What it does NOT do:
    - Run the task on a worker. That's the dev smoke (real Xero edit
      → real handler → real worker), which is the only way to exercise
      the full pipeline anyway.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Django's @override_settings doesn't propagate to celery_app.conf
        # for broker_url (it's read at app-init, not live). Force it.
        cls._was_broker = celery_app.conf.broker_url
        cls._was_eager = celery_app.conf.task_always_eager
        celery_app.conf.update(
            broker_url=TEST_BROKER_URL,
            task_always_eager=False,
        )

    @classmethod
    def tearDownClass(cls):
        celery_app.conf.update(
            broker_url=cls._was_broker,
            task_always_eager=cls._was_eager,
        )
        super().tearDownClass()

    def setUp(self) -> None:
        self.factory = RequestFactory()
        self.url = reverse("xero_webhook")
        # Safety: refuse to run if we'd be writing to dev's broker.
        assert celery_app.conf.broker_url == TEST_BROKER_URL, (
            f"Refusing to run broker test — broker_url is "
            f"{celery_app.conf.broker_url}, must be {TEST_BROKER_URL} to "
            "avoid feeding dev's celery worker bogus tasks."
        )
        self.redis = redis.Redis.from_url(TEST_BROKER_URL)
        self.redis.flushdb()  # clean slate per test

    def tearDown(self) -> None:
        self.redis.flushdb()
        self.redis.close()

    def _signed_post(self, body: bytes):
        return self.factory.post(
            self.url,
            data=body,
            content_type="application/json",
            HTTP_X_XERO_SIGNATURE=_sign(body),
        )

    def test_handler_dispatches_to_real_broker_without_blocking(self) -> None:
        """The 2026-05-01 incident: handler exceeded Xero's 5s timeout
        because sync_single_invoice ran inline. With a real broker and
        eager mode off, the handler must complete its dispatch in well
        under Xero's redelivery window — no matter how slow the task is.

        Also proves the event payload survives JSON serialization through
        the broker, which eager mode silently bypasses.
        """
        body = json.dumps({"events": [_event()]}).encode("utf-8")
        request = self._signed_post(body)

        start = time.perf_counter()
        response = XeroWebhookView.as_view()(request)
        elapsed = time.perf_counter() - start

        self.assertEqual(response.status_code, 200)
        self.assertLess(
            elapsed,
            0.5,
            f"Handler took {elapsed:.3f}s with a real broker — must be "
            "<0.5s to stay well under Xero's 5s redelivery timeout. "
            "Synchronous regression.",
        )

        # The default queue is "celery"; .delay() pushes a JSON-encoded
        # message there. If serialization had failed, .delay() would have
        # raised before we got here.
        queue_len = self.redis.llen("celery")
        self.assertEqual(
            queue_len,
            1,
            f"Expected exactly one task on the broker, found {queue_len}.",
        )

    def test_multiple_events_all_dispatch_via_broker(self) -> None:
        """Five events come in together — the original burst pattern that
        crossed the >4-event threshold and triggered the loop. Handler must
        dispatch them all and return fast; the broker must hold them all."""
        events = [_event(resource_id=f"inv-{i}", event_id=f"e{i}") for i in range(5)]
        body = json.dumps({"events": events}).encode("utf-8")
        request = self._signed_post(body)

        start = time.perf_counter()
        response = XeroWebhookView.as_view()(request)
        elapsed = time.perf_counter() - start

        self.assertEqual(response.status_code, 200)
        self.assertLess(
            elapsed,
            0.5,
            f"5-event burst handler took {elapsed:.3f}s — the original "
            "bug condition. Must stay <0.5s.",
        )
        self.assertEqual(self.redis.llen("celery"), 5)
