"""Tests for the Xero day-quota floor: helper and gate sites.

The floor (`settings.XERO_AUTOMATED_DAY_FLOOR`) reserves the last N day-quota
calls for known-cost user-initiated actions. Sync paths and the webhook
processing task refuse to call Xero once the active XeroApp row's snapshot
says `day_remaining <= floor`. See
docs/plans/2026-05-02-xero-day-quota-floor.md and
docs/plans/2026-05-03-xero-app-credentials-quota.md.

Also covers the stock-write refactor that landed alongside the gate work:
``sync_all_local_stock_to_xero`` now upserts via ``update_or_create_items``
(batches of 50) rather than per-item ``update_item`` calls.
"""

from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone as dj_timezone

from apps.purchasing.models import Stock
from apps.workflow.api.xero.client import quota_floor_breached
from apps.workflow.api.xero.sync import sync_xero_data
from apps.workflow.models import XeroApp


def _active_app(**overrides):
    """Create an active XeroApp row with sensible defaults."""
    defaults = {
        "label": "Primary",
        "client_id": "test-c",
        "client_secret": "s",
        "redirect_uri": "https://e/cb",
        "is_active": True,
    }
    defaults.update(overrides)
    return XeroApp.objects.create(**defaults)


def _set_quota(day_remaining, minute_remaining=60, snapshot_age_seconds=0):
    """Set the active XeroApp's snapshot to specific values.

    Creates an active row if none exists, otherwise updates the existing one.
    """
    snapshot_at = dj_timezone.now() - timedelta(seconds=snapshot_age_seconds)
    if XeroApp.objects.filter(is_active=True).exists():
        XeroApp.objects.filter(is_active=True).update(
            day_remaining=day_remaining,
            minute_remaining=minute_remaining,
            snapshot_at=snapshot_at,
        )
    else:
        _active_app(
            day_remaining=day_remaining,
            minute_remaining=minute_remaining,
            snapshot_at=snapshot_at,
        )


class QuotaFloorBreachedHelperTests(TestCase):
    def test_no_active_row_returns_false(self):
        # Nothing to gate against — fall through and let the call go.
        self.assertFalse(quota_floor_breached(100))

    def test_missing_snapshot_returns_false(self):
        # Active row exists but no API call has happened yet.
        _active_app()
        self.assertFalse(quota_floor_breached(100))

    def test_day_remaining_above_floor_returns_false(self):
        _set_quota(day_remaining=200)
        self.assertFalse(quota_floor_breached(100))

    def test_day_remaining_at_floor_returns_true(self):
        _set_quota(day_remaining=100)
        self.assertTrue(quota_floor_breached(100))

    def test_day_remaining_below_floor_returns_true(self):
        _set_quota(day_remaining=50)
        self.assertTrue(quota_floor_breached(100))

    def test_day_remaining_none_returns_false(self):
        # First-call response sometimes omits day_remaining.
        _active_app(
            day_remaining=None,
            minute_remaining=60,
            snapshot_at=dj_timezone.now(),
        )
        self.assertFalse(quota_floor_breached(100))

    def test_stale_snapshot_returns_false(self):
        # Snapshot older than the staleness window — let the next call
        # probe Xero fresh; the rolling 24h window has freed quota since.
        _set_quota(day_remaining=10, snapshot_age_seconds=60 * 60)
        self.assertFalse(quota_floor_breached(100))


@override_settings(XERO_AUTOMATED_DAY_FLOOR=100)
class RateLimit429WritesToActiveRowTests(TestCase):
    """Without this, the snapshot only updates on 2xx — and the gate stays
    unarmed precisely when it's most needed (right after Xero just told us
    the day quota is exhausted). Quota writes target the row whose
    credentials made the call (via app_id), not the active row at the
    moment of write."""

    def _run_handle_rate_limit(
        self, *, app_id, day_remaining, minute_remaining, problem
    ):
        from apps.workflow.api.xero.client import RateLimitedRESTClient

        # Build a minimal fake exception that matches what the SDK passes in.
        exc = MagicMock()
        exc.headers = {
            "Retry-After": "60",
            "X-Rate-Limit-Problem": problem,
            "X-DayLimit-Remaining": str(day_remaining),
            "X-MinLimit-Remaining": str(minute_remaining),
        }

        # __init__ side-steps the real super().__init__ to avoid building a
        # urllib3 pool — we're only exercising _handle_rate_limit's logic.
        client = RateLimitedRESTClient.__new__(RateLimitedRESTClient)
        client.app_id = app_id
        client._rate_limit_hits = 0

        try:
            client._handle_rate_limit(exc)
        except Exception:
            # day-limit branch raises; we don't care about that here.
            pass

    def test_minute_limit_429_writes_snapshot_to_bound_row(self):
        row = _active_app()
        with patch("apps.workflow.api.xero.client.time.sleep"):
            self._run_handle_rate_limit(
                app_id=row.id,
                day_remaining=42,
                minute_remaining=0,
                problem="minute",
            )
        row.refresh_from_db()
        self.assertEqual(row.day_remaining, 42)
        self.assertEqual(row.minute_remaining, 0)
        self.assertIsNotNone(row.snapshot_at)

    def test_day_limit_429_writes_snapshot_and_last_429_at(self):
        row = _active_app()
        with patch(
            "apps.workflow.api.xero.client.persist_app_error",
            return_value=None,
        ):
            self._run_handle_rate_limit(
                app_id=row.id,
                day_remaining=0,
                minute_remaining=60,
                problem="day",
            )
        row.refresh_from_db()
        self.assertEqual(row.day_remaining, 0)
        self.assertIsNotNone(row.last_429_at)

    def test_writes_to_bound_row_not_active_row(self):
        # Construct a client bound to row B's id while row A is currently
        # active. The 429 must update B, not A.
        a = _active_app(client_id="c-a", label="A", is_active=True)
        b = XeroApp.objects.create(
            label="B",
            client_id="c-b",
            client_secret="s",
            redirect_uri="https://e/cb",
            is_active=False,
        )
        with patch("apps.workflow.api.xero.client.time.sleep"):
            self._run_handle_rate_limit(
                app_id=b.id,
                day_remaining=99,
                minute_remaining=5,
                problem="minute",
            )
        a.refresh_from_db()
        b.refresh_from_db()
        self.assertIsNone(a.day_remaining)
        self.assertEqual(b.day_remaining, 99)


@override_settings(XERO_AUTOMATED_DAY_FLOOR=100)
class StoreQuotaSnapshotWritesToBoundRowTests(TestCase):
    """The 2xx path: _store_quota_snapshot updates the bound row's quota
    fields directly."""

    def test_2xx_updates_bound_row(self):
        from apps.workflow.api.xero.client import RateLimitedRESTClient

        row = _active_app()
        client = RateLimitedRESTClient.__new__(RateLimitedRESTClient)
        client.app_id = row.id
        client._store_quota_snapshot(4321, 55)

        row.refresh_from_db()
        self.assertEqual(row.day_remaining, 4321)
        self.assertEqual(row.minute_remaining, 55)
        self.assertIsNotNone(row.snapshot_at)

    def test_no_app_id_silently_skips(self):
        from apps.workflow.api.xero.client import RateLimitedRESTClient

        # Pre-existing row stays untouched when client has no app_id.
        row = _active_app()
        client = RateLimitedRESTClient.__new__(RateLimitedRESTClient)
        client.app_id = None
        client._store_quota_snapshot(1234, 10)

        row.refresh_from_db()
        self.assertIsNone(row.day_remaining)


@override_settings(XERO_AUTOMATED_DAY_FLOOR=100)
class SynchroniseXeroDataOrchestratorGateTests(TestCase):
    """`sync_xero_pay_items` runs first inside the orchestrator and is
    otherwise unguarded. Without an orchestrator-top gate the per-page
    gate inside ``sync_xero_data`` never gets a chance — pay items 429
    before we reach it."""

    def setUp(self):
        cache.delete("xero_sync_lock")

    def tearDown(self):
        cache.delete("xero_sync_lock")

    def test_floor_breached_skips_entire_pipeline(self):
        from apps.workflow.api.xero.sync import synchronise_xero_data

        _set_quota(day_remaining=0)

        with (
            patch(
                "apps.workflow.api.xero.payroll.sync_xero_pay_items"
            ) as mock_pay_items,
            patch("apps.workflow.api.xero.sync.deep_sync_xero_data") as mock_deep,
            patch(
                "apps.workflow.api.xero.sync.one_way_sync_all_xero_data"
            ) as mock_normal,
        ):
            events = list(synchronise_xero_data())

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["severity"], "warning")
        self.assertIn("Xero day quota at floor", events[0]["message"])
        mock_pay_items.assert_not_called()
        mock_deep.assert_not_called()
        mock_normal.assert_not_called()


@override_settings(XERO_AUTOMATED_DAY_FLOOR=100)
class SyncXeroDataPerPageGateTests(TestCase):
    """sync_xero_data must check the floor before each fetch.

    The gate is per-page (inside the while loop), not per-entity (function
    entry), because a single paginated entity can drain thousands of calls.
    """

    def setUp(self):
        # Snapshot now lives on XeroApp rows — cleared automatically by
        # TestCase's per-test transaction rollback.
        pass

    def _consume(self, generator):
        """Fully iterate the generator and return its emitted events."""
        return list(generator)

    def test_floor_breached_yields_warning_and_skips_fetch(self):
        _set_quota(day_remaining=50)
        fetch = MagicMock()  # would explode if called

        events = self._consume(
            sync_xero_data(
                xero_entity_type="invoices",
                our_entity_type="invoices",
                xero_api_fetch_function=fetch,
                sync_function=lambda items: None,
                last_modified_time="2026-01-01",
                xero_tenant_id="test-tenant",
            )
        )

        fetch.assert_not_called()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["severity"], "warning")
        self.assertIn("quota at floor", events[0]["message"])
        self.assertEqual(events[0]["progress"], 0.0)

    def test_above_floor_proceeds_normally(self):
        _set_quota(day_remaining=500)
        # One page returning fewer than page_size → loop completes after one fetch.
        page = MagicMock()
        page.invoices = []  # empty list ends the loop
        fetch = MagicMock(return_value=page)

        events = self._consume(
            sync_xero_data(
                xero_entity_type="invoices",
                our_entity_type="invoices",
                xero_api_fetch_function=fetch,
                sync_function=lambda items: None,
                last_modified_time="2026-01-01",
                xero_tenant_id="test-tenant",
            )
        )

        fetch.assert_called_once()
        # No warning event.
        self.assertFalse(any(e.get("severity") == "warning" for e in events))


@override_settings(XERO_AUTOMATED_DAY_FLOOR=100)
class WebhookTaskGateTests(TestCase):
    """process_xero_webhook_event must early-return without Xero calls when
    the floor is breached, and must NOT raise (Celery would retry indefinitely)."""

    def setUp(self):
        # Snapshot now lives on XeroApp rows — cleared automatically by
        # TestCase's per-test transaction rollback.
        pass

    def _event(self):
        return {
            "eventCategory": "INVOICE",
            "resourceId": "inv-1",
            "tenantId": "tenant-abc",
            "eventId": "evt-1",
        }

    def test_floor_breached_skips_without_calling_sync(self):
        from apps.workflow.tasks import process_xero_webhook_event

        _set_quota(day_remaining=50)

        with (
            patch("apps.workflow.tasks.XeroSyncService") as mock_svc,
            patch("apps.workflow.tasks.sync_single_invoice") as mock_invoice,
            patch("apps.workflow.tasks.sync_single_contact") as mock_contact,
            patch("apps.workflow.tasks.CompanyDefaults.get_solo") as mock_solo,
        ):
            # Should not raise, should not even read CompanyDefaults.
            process_xero_webhook_event("tenant-abc", self._event())

        mock_svc.assert_not_called()
        mock_invoice.assert_not_called()
        mock_contact.assert_not_called()
        mock_solo.assert_not_called()

    def test_above_floor_proceeds(self):
        from apps.workflow.tasks import process_xero_webhook_event

        _set_quota(day_remaining=500)

        with (
            patch("apps.workflow.tasks.XeroSyncService"),
            patch("apps.workflow.tasks.sync_single_invoice") as mock_invoice,
            patch(
                "apps.workflow.tasks.CompanyDefaults.get_solo",
                return_value=SimpleNamespace(xero_tenant_id="tenant-abc"),
            ),
        ):
            process_xero_webhook_event("tenant-abc", self._event())

        mock_invoice.assert_called_once()


class StockBatchedUpsertRefactorTests(TestCase):
    """The stock-write refactor: per-item ``update_item`` was replaced with
    a single ``update_or_create_items`` per batch of up to 50 items. New
    items have no ``ItemID`` in the payload (Xero creates them); items
    linked-by-Code carry the existing ``ItemID`` (Xero updates them)."""

    def setUp(self):
        # sync_all_local_stock_to_xero now constructs AccountingApi via
        # get_active_client(), which requires an active XeroApp row.
        # The patched AccountingApi swallows the actual SDK calls — but
        # the row needs to exist so get_active_client() can read it.
        _active_app(client_id="stock-test", access_token="x", refresh_token="y")
        from apps.workflow.api.xero import active_app

        active_app._reset_client_cache()

    def tearDown(self):
        from apps.workflow.api.xero import active_app

        active_app._reset_client_cache()

    def test_upsert_batch_called_with_mixed_create_and_update_payload(self):
        from apps.workflow.api.xero import stock_sync

        # Two local items: one already in Xero by Code, one brand new.
        existing_in_xero = Stock.objects.create(
            description="Existing-by-code item",
            item_code="ALR-EXISTS",
            quantity=Decimal("1.00"),
            unit_cost=Decimal("10.00"),
            unit_revenue=Decimal("12.00"),
        )
        brand_new = Stock.objects.create(
            description="Brand new item",
            item_code="ALR-NEW",
            quantity=Decimal("1.00"),
            unit_cost=Decimal("20.00"),
            unit_revenue=Decimal("25.00"),
        )

        # Lookup returns the existing match for ALR-EXISTS, none for ALR-NEW.
        existing_xero_item = SimpleNamespace(
            item_id="xero-existing-id", code="ALR-EXISTS"
        )
        lookup = {"ALR-EXISTS": existing_xero_item}

        # Response from update_or_create_items: items echoed back with item_id.
        # Xero assigns a new id to the create, returns the same id for the update.
        response = SimpleNamespace(
            items=[
                SimpleNamespace(item_id="xero-existing-id", code="ALR-EXISTS"),
                SimpleNamespace(item_id="xero-new-id", code="ALR-NEW"),
            ]
        )

        mock_api = MagicMock()
        mock_api.update_or_create_items.return_value = response

        with (
            patch.object(stock_sync, "AccountingApi", return_value=mock_api),
            patch.object(stock_sync, "get_tenant_id", return_value="tenant-zzz"),
            patch.object(stock_sync, "fetch_all_xero_items", return_value=lookup),
            # The function reads XeroAccount for purchase/sales — return
            # SimpleNamespace stubs that satisfy the attribute reads in the
            # payload builder.
            patch.object(
                stock_sync.XeroAccount,
                "objects",
                MagicMock(
                    filter=MagicMock(
                        return_value=MagicMock(
                            first=MagicMock(
                                return_value=SimpleNamespace(account_code="300")
                            )
                        )
                    )
                ),
            ),
        ):
            result = stock_sync.sync_all_local_stock_to_xero()

        # One batched upsert call, never the old per-item update_item.
        self.assertEqual(mock_api.update_or_create_items.call_count, 1)
        self.assertFalse(mock_api.update_item.called)
        self.assertFalse(mock_api.create_items.called)

        # Inspect the payload Xero received: existing item has ItemID set,
        # new item does not.
        _args, kwargs = mock_api.update_or_create_items.call_args
        items_payload = kwargs["items"]["Items"]
        self.assertEqual(len(items_payload), 2)
        by_code = {p["Code"]: p for p in items_payload}
        self.assertEqual(by_code["ALR-EXISTS"]["ItemID"], "xero-existing-id")
        self.assertNotIn("ItemID", by_code["ALR-NEW"])

        # Both local items got their xero_id and xero_last_synced bumped from
        # the response.
        existing_in_xero.refresh_from_db()
        brand_new.refresh_from_db()
        self.assertEqual(existing_in_xero.xero_id, "xero-existing-id")
        self.assertEqual(brand_new.xero_id, "xero-new-id")
        self.assertIsNotNone(existing_in_xero.xero_last_synced)
        self.assertIsNotNone(brand_new.xero_last_synced)

        self.assertEqual(result["synced_count"], 2)
        self.assertEqual(result["failed_count"], 0)
