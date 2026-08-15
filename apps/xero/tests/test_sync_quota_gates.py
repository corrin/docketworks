"""The day-quota floor gates in the sync engine, and the sync cursors.

Business case: when quota is reserved for office users, automated sync must
abort as an operational abort — never report success after doing no work, and
never burn the reserved calls page by page. The cursor tests pin the engine's
high-water-mark contract: a suppressed page still advances the cursor, and a
fresh install falls back to the database's own high-water mark.
"""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from django.core.cache import cache, caches
from django.test import override_settings
from django.utils import timezone
from pytest_django.fixtures import SettingsWrapper

from apps.accounting.models import Invoice
from apps.company.models import Company
from apps.core.models import AppError, CompanyDefaults
from apps.purchasing.models import Stock
from apps.xero import stock_sync
from apps.xero.client import XeroQuotaFloorReached
from apps.xero.models import XeroAccount, XeroSyncCursor
from apps.xero.sync import get_sync_cursor, sync_xero_data, synchronise_xero_data
from apps.xero.sync_constants import SYNC_STATUS_KEY
from apps.xero.sync_worker import xero_sync_task

from .conftest import set_active_quota

# Sync state lives on the "shared" alias (Redis in prod, LocMem in tests).
# The legacy "xero_sync_lock" in synchronise_xero_data stays on the default cache.
_shared = caches["shared"]


def _set_company_floor(floor: int = 100) -> None:
    CompanyDefaults.objects.filter(pk=1).update(xero_automated_day_floor=floor)


@pytest.mark.django_db
class TestSynchroniseXeroDataOrchestratorGate:
    """``sync_xero_pay_items`` runs first inside the orchestrator and is
    otherwise unguarded. Without an orchestrator-top gate the per-page gate
    inside ``sync_xero_data`` never gets a chance — pay items 429 before we
    reach it.
    """

    @pytest.fixture(autouse=True)
    def _clean_lock(self) -> Iterator[None]:
        cache.delete("xero_sync_lock")
        _set_company_floor()
        yield
        cache.delete("xero_sync_lock")

    def test_floor_breached_raises_before_pipeline(self) -> None:
        # The orchestrator must raise XeroQuotaFloorReached, NOT yield a
        # warning event and return. A returned generator looks like a
        # successful empty stream to the worker task, which would then emit
        # sync_status:"success" — masking the abort.
        set_active_quota(day_remaining=0)

        with (
            patch("apps.xero.sync.sync_xero_pay_items") as mock_pay_items,
            patch("apps.xero.sync.deep_sync_xero_data") as mock_deep,
            patch("apps.xero.sync.one_way_sync_all_xero_data") as mock_normal,
            pytest.raises(XeroQuotaFloorReached),
        ):
            list(synchronise_xero_data())

        assert not mock_pay_items.called
        assert not mock_deep.called
        assert not mock_normal.called

    def test_floor_breached_does_not_advance_last_sync_timestamps(self) -> None:
        # A quota abort must not advance last-sync timestamps; otherwise the
        # next real sync skips work and stale Xero data stays hidden for days.
        set_active_quota(day_remaining=0)

        with pytest.raises(XeroQuotaFloorReached):
            list(synchronise_xero_data())

        defaults = CompanyDefaults.get_solo()
        assert defaults.last_xero_sync is None
        assert defaults.last_xero_deep_sync is None


@pytest.mark.django_db
class TestSyncXeroDataPerPageGate:
    """The gate is per-page (inside the while loop), not per-entity: a single
    paginated entity can drain thousands of calls between entity boundaries.
    """

    @pytest.fixture(autouse=True)
    def _floor(self, settings: SettingsWrapper) -> None:
        # pytest-django forces DEBUG=False, which arms the production-tenant
        # guard; release it so the quota gate is what these tests exercise.
        settings.DEBUG = True
        _set_company_floor()

    def test_floor_breached_raises_before_fetch(self) -> None:
        set_active_quota(day_remaining=50)
        fetch = MagicMock()  # would explode if called

        with pytest.raises(XeroQuotaFloorReached):
            list(
                sync_xero_data(
                    xero_entity_type="invoices",
                    our_entity_type="invoices",
                    xero_api_fetch_function=fetch,
                    sync_function=lambda _items: None,
                    last_modified_time="2026-01-01",
                    xero_tenant_id="test-tenant",
                )
            )

        assert not fetch.called

    def test_above_floor_proceeds_normally(self) -> None:
        set_active_quota(day_remaining=500)
        # One page returning no items ends the loop after a single fetch.
        fetch = MagicMock(return_value=SimpleNamespace(invoices=[]))

        with patch("apps.xero.sync.time.sleep"):
            events = list(
                sync_xero_data(
                    xero_entity_type="invoices",
                    our_entity_type="invoices",
                    xero_api_fetch_function=fetch,
                    sync_function=lambda _items: None,
                    last_modified_time="2026-01-01",
                    xero_tenant_id="test-tenant",
                )
            )

        assert fetch.call_count == 1
        assert not any(event.get("severity") == "warning" for event in events)
        assert events[-1].get("status") == "Completed"


@pytest.mark.django_db
class TestStockBatchedUpsert:
    """Stock pushes go through one ``update_or_create_items`` call per batch of
    50 — never the old per-item ``update_item``. New items carry no ``ItemID``
    (Xero creates them); items linked-by-Code carry the existing ``ItemID``
    (Xero updates them).
    """

    def test_upsert_batch_called_with_mixed_create_and_update_payload(self) -> None:
        _set_company_floor()
        # Real chart-of-accounts rows satisfy the payload builder's lookups.
        XeroAccount.objects.create(
            xero_id=uuid4(),
            account_code="300",
            account_name="Purchases",
            xero_last_modified=timezone.now(),
            raw_json={},
        )
        XeroAccount.objects.create(
            xero_id=uuid4(),
            account_code="200",
            account_name="Sales",
            xero_last_modified=timezone.now(),
            raw_json={},
        )

        # Two local items: one already in Xero by Code, one brand new.
        existing_in_xero = Stock.objects.create(
            description="Existing-by-code item",
            item_code="ALR-EXISTS",
            quantity=Decimal("1.00"),
            unit_cost=Decimal("10.00"),
            unit_revenue=Decimal("12.00"),
            source="manual",
        )
        brand_new = Stock.objects.create(
            description="Brand new item",
            item_code="ALR-NEW",
            quantity=Decimal("1.00"),
            unit_cost=Decimal("20.00"),
            unit_revenue=Decimal("25.00"),
            source="manual",
        )

        # Lookup returns the existing match for ALR-EXISTS, none for ALR-NEW.
        lookup = {"ALR-EXISTS": SimpleNamespace(item_id="xero-existing-id", code="ALR-EXISTS")}

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
            patch.object(stock_sync, "get_api_client", return_value=MagicMock()),
            patch.object(stock_sync, "get_tenant_id", return_value="tenant-zzz"),
            patch.object(stock_sync, "fetch_all_xero_items", return_value=lookup),
            patch("apps.xero.stock_sync.time.sleep"),
        ):
            result = stock_sync.sync_all_local_stock_to_xero()

        # One batched upsert call, never the old per-item paths.
        assert mock_api.update_or_create_items.call_count == 1
        assert not mock_api.update_item.called
        assert not mock_api.create_items.called

        # The payload Xero received: existing item has ItemID set, new does not.
        _args, kwargs = mock_api.update_or_create_items.call_args
        items_payload = kwargs["items"]["Items"]
        assert len(items_payload) == 2
        by_code = {payload["Code"]: payload for payload in items_payload}
        assert by_code["ALR-EXISTS"]["ItemID"] == "xero-existing-id"
        assert "ItemID" not in by_code["ALR-NEW"]

        # Both local items got xero_id and xero_last_synced from the response.
        existing_in_xero.refresh_from_db()
        brand_new.refresh_from_db()
        assert existing_in_xero.xero_id == "xero-existing-id"
        assert brand_new.xero_id == "xero-new-id"
        assert existing_in_xero.xero_last_synced is not None
        assert brand_new.xero_last_synced is not None

        assert result["synced_count"] == 2
        assert result["failed_count"] == 0


@pytest.mark.django_db
class TestWorkerAbortedBranch:
    """``xero_sync_task`` must treat ``XeroQuotaFloorReached`` as an
    operational abort: emit ``sync_status:"aborted"`` (NOT "success", NOT a
    generic error), do NOT persist an AppError (24+ rows/day at the floor
    would be noise), and release the task lock.
    """

    TASK_ID = "test-task-quota"

    @pytest.fixture(autouse=True)
    def _clean_shared_cache(self) -> Iterator[None]:
        _shared.delete(SYNC_STATUS_KEY)
        _shared.delete(f"xero_sync_messages_{self.TASK_ID}")
        yield
        _shared.delete(SYNC_STATUS_KEY)
        _shared.delete(f"xero_sync_messages_{self.TASK_ID}")

    def test_quota_floor_emits_aborted_marker_and_skips_persist_app_error(self) -> None:
        _shared.set(f"xero_sync_messages_{self.TASK_ID}", [], timeout=60)
        _shared.set(SYNC_STATUS_KEY, self.TASK_ID, timeout=60)

        def _gen() -> Iterator[dict[str, str]]:
            yield {"entity": "contacts", "severity": "info", "message": "starting"}
            raise XeroQuotaFloorReached("Skipping sync: Xero day quota at floor (100)")

        app_errors_before = AppError.objects.count()
        # No enable_xero_sync patch: the worker no longer reads that gate — the
        # engine owns it and raises XeroSyncDisabled, which is a different
        # branch from the quota abort under test here.
        with (
            override_settings(XERO_READONLY=False),
            patch("apps.xero.sync.synchronise_xero_data", return_value=_gen()),
        ):
            xero_sync_task(self.TASK_ID)

        # Lock released.
        assert _shared.get(SYNC_STATUS_KEY) is None
        # No AppError row — the abort is not a defect to investigate.
        assert AppError.objects.count() == app_errors_before

        msgs = _shared.get(f"xero_sync_messages_{self.TASK_ID}", [])
        final = msgs[-1]
        assert final["sync_status"] == "aborted"
        # The penultimate message explains the abort. Severity is "warning",
        # not "error": the SSE stream derives its terminal sync_status from
        # error-severity messages, and an aborted run must not read back as
        # a failed one (review fix over v1, which used "error").
        penultimate = msgs[-2]
        assert penultimate["severity"] == "warning"
        assert "abort" in penultimate["message"].lower()


@pytest.mark.django_db
class TestSyncCursors:
    """Per-entity high-water marks: what the hourly sync resumes from."""

    @pytest.fixture(autouse=True)
    def _debug_on(self, settings: SettingsWrapper) -> None:
        # As in TestSyncXeroDataPerPageGate: keep the tenant guard released.
        settings.DEBUG = True

    def test_cursor_advances_over_fetched_items_even_when_all_filtered(self) -> None:
        # E2E-artifact suppression drops items AFTER the fetch; the cursor must
        # advance over the fetched set or the same page is refetched from Xero
        # every hour, forever.
        older = datetime(2026, 6, 1, 10, 0, tzinfo=UTC)
        newer = datetime(2026, 6, 2, 12, 30, tzinfo=UTC)
        page = SimpleNamespace(
            invoices=[
                SimpleNamespace(updated_date_utc=older),
                SimpleNamespace(updated_date_utc=newer),
            ]
        )
        fetch = MagicMock(return_value=page)
        sync_function = MagicMock()

        with (
            patch("apps.xero.sync.drop_e2e_artifacts", return_value=[]),
            patch("apps.xero.sync.time.sleep"),
        ):
            list(
                sync_xero_data(
                    xero_entity_type="invoices",
                    our_entity_type="invoices",
                    xero_api_fetch_function=fetch,
                    sync_function=sync_function,
                    last_modified_time="2026-01-01",
                    xero_tenant_id="test-tenant",
                    entity_key="invoices",
                )
            )

        assert not sync_function.called
        cursor = XeroSyncCursor.objects.get(entity_key="invoices")
        assert cursor.last_modified == newer

    def test_get_sync_cursor_backs_off_one_second(self) -> None:
        # The overlap window: an object saved in the same second as the last
        # run's newest item must not be skipped by the next run.
        last = datetime(2026, 6, 3, 9, 0, 0, tzinfo=UTC)
        XeroSyncCursor.objects.create(entity_key="invoices", last_modified=last)

        assert get_sync_cursor("invoices", Invoice) == (last - timedelta(seconds=1)).isoformat()

    def test_first_run_falls_back_to_model_high_water_mark(self) -> None:
        # No cursor yet (first sync after deployment): resume from the newest
        # xero_last_modified already in the database, minus the same backoff.
        newest = timezone.now() + timedelta(days=1)
        Company.objects.create(
            name="High Water Mark Ltd",
            xero_contact_id="contact-hwm-1",
            xero_last_modified=newest,
        )

        assert get_sync_cursor("contacts", Company) == (newest - timedelta(seconds=1)).isoformat()

    def test_first_run_with_empty_table_falls_back_to_epoch(self) -> None:
        assert get_sync_cursor("invoices", Invoice) == "2000-01-01T00:00:00Z"
