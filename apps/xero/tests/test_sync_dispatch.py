"""Dispatching Xero sync runs: the HTTP trigger, the lock, and the worker.

Business risks: a lock that leaks after a failed dispatch blocks every future
sync for the 4-hour lock timeout; a worker that swallows real errors (or
screams about routine quota aborts) poisons the operator's signal either way.
The beat entries that drive the hourly/weekly runs are pinned in
``config/tests/test_celery_beat.py`` — layering forbids apps importing config.
"""

from collections.abc import Iterator
from unittest.mock import MagicMock, call, patch

import pytest
from django.core.cache import caches
from django.test import Client, override_settings

from apps.core.models import AppError, CompanyDefaults
from apps.xero.client import XeroQuotaFloorReached
from apps.xero.sync_constants import LOCK_TIMEOUT, SYNC_STATUS_KEY
from apps.xero.sync_service import XeroSyncService
from apps.xero.sync_worker import xero_sync_task

SYNC_URL = "/api/xero/sync/"
SYNC_INFO_URL = "/api/xero/sync-info/"

_shared = caches["shared"]


@pytest.fixture(autouse=True)
def _clean_sync_cache() -> Iterator[None]:
    """Sync state lives on the shared cache alias, which outlives a test's
    transaction rollback — clear it so a leaked lock cannot couple tests."""
    _shared.clear()
    yield
    _shared.clear()


@pytest.mark.django_db
class TestXeroSyncCreate:
    """POST /api/xero/sync/ — the manual trigger behind the Sync button."""

    def test_office_staff_only(self, non_office_api: Client) -> None:
        assert non_office_api.post(SYNC_URL).status_code == 403

    def test_lock_held_returns_409_with_the_active_task_id(self, api: Client) -> None:
        """The 409 body carries the RUNNING task's id so the client can attach
        to that run's progress stream instead of believing it started one."""
        _shared.set(SYNC_STATUS_KEY, "task-already-running")

        response = api.post(SYNC_URL)

        assert response.status_code == 409
        body = response.json()
        assert body["status"] == "already_running"
        assert body["task_id"] == "task-already-running"
        # The refused attempt must not have stolen or cleared the lock.
        assert _shared.get(SYNC_STATUS_KEY) == "task-already-running"

    def test_invalid_token_returns_401_and_releases_the_lock(self, api: Client) -> None:
        provider = MagicMock()
        provider.get_valid_token.return_value = None

        with patch("apps.xero.sync_service.get_provider", return_value=provider):
            response = api.post(SYNC_URL)

        assert response.status_code == 401
        assert response.json()["redirect_to_auth"] is True
        assert _shared.get(SYNC_STATUS_KEY) is None

    def test_dispatch_returns_202_with_task_id_and_holds_the_lock(self, api: Client) -> None:
        provider = MagicMock()
        provider.get_valid_token.return_value = {"access_token": "t"}

        with (
            patch("apps.xero.sync_service.get_provider", return_value=provider),
            patch.object(xero_sync_task, "delay") as mock_delay,
        ):
            response = api.post(SYNC_URL)

        assert response.status_code == 202
        body = response.json()
        assert body["status"] == "started"
        task_id = body["task_id"]
        assert task_id
        mock_delay.assert_called_once_with(task_id)
        # The lock value IS the task id, so readers can attach to the run.
        assert _shared.get(SYNC_STATUS_KEY) == task_id


@pytest.mark.django_db
class TestStartSyncLockRelease:
    """A failed dispatch must never leave the lock behind.

    The lock times out after 4 hours — a leak here means four hours of
    "already running" refusals with no sync actually running.
    """

    def test_token_check_failure_releases_the_lock(self) -> None:
        with (
            patch("apps.xero.sync_service.get_provider", side_effect=RuntimeError("provider down")),
            pytest.raises(RuntimeError),
        ):
            XeroSyncService.start_sync()

        assert _shared.get(SYNC_STATUS_KEY) is None

    def test_broker_failure_releases_the_lock(self) -> None:
        provider = MagicMock()
        provider.get_valid_token.return_value = {"access_token": "t"}

        with (
            patch("apps.xero.sync_service.get_provider", return_value=provider),
            patch.object(xero_sync_task, "delay", side_effect=RuntimeError("broker down")),
            pytest.raises(RuntimeError),
        ):
            XeroSyncService.start_sync()

        assert _shared.get(SYNC_STATUS_KEY) is None

    def _steal_the_lock(self) -> None:
        """Stand in for this attempt's lease expiring and a newer run acquiring."""
        _shared.set(SYNC_STATUS_KEY, "newer-run", timeout=60)

    def test_token_check_failure_does_not_release_a_newer_runs_lock(self) -> None:
        """Every rollback path is owner-checked. Deleting unconditionally frees
        the NEXT run's lock, which is exactly the concurrent sync the lock
        exists to prevent — the failure mode is silent until two runs write the
        same entities."""

        def _steal_then_fail() -> object:
            self._steal_the_lock()
            raise RuntimeError("provider down")

        with (
            patch("apps.xero.sync_service.get_provider", side_effect=_steal_then_fail),
            pytest.raises(RuntimeError),
        ):
            XeroSyncService.start_sync()

        assert _shared.get(SYNC_STATUS_KEY) == "newer-run"

    def test_invalid_token_does_not_release_a_newer_runs_lock(self) -> None:
        provider = MagicMock()
        # Returns None (no token) after stealing the lock, so this exercises
        # the no_valid_token rollback rather than the exception one.
        provider.get_valid_token.side_effect = self._steal_the_lock

        with patch("apps.xero.sync_service.get_provider", return_value=provider):
            result = XeroSyncService.start_sync()

        assert result.reason == "no_valid_token"
        assert _shared.get(SYNC_STATUS_KEY) == "newer-run"

    def test_broker_failure_does_not_release_a_newer_runs_lock(self) -> None:
        provider = MagicMock()
        provider.get_valid_token.return_value = {"access_token": "t"}

        def _steal_then_fail(_task_id: str) -> None:
            self._steal_the_lock()
            raise RuntimeError("broker down")

        with (
            patch("apps.xero.sync_service.get_provider", return_value=provider),
            patch.object(xero_sync_task, "delay", side_effect=_steal_then_fail),
            pytest.raises(RuntimeError),
        ):
            XeroSyncService.start_sync()

        assert _shared.get(SYNC_STATUS_KEY) == "newer-run"


@pytest.mark.django_db
class TestSyncInfo:
    """GET /api/xero/sync-info/ — the sync status table."""

    def test_last_syncs_covers_pay_items_and_every_configured_entity(self, api: Client) -> None:
        """An entity missing from this table is one whose sync can silently
        stop: the operator's page simply never shows it going stale."""
        response = api.get(SYNC_INFO_URL)

        assert response.status_code == 200
        body = response.json()
        # Literal list, not derived from ENTITY_CONFIGS: deleting an entity
        # from the sync must fail THIS pin, not silently shrink both sides.
        assert list(body["last_syncs"].keys()) == [
            "pay_items",
            "accounts",
            "contacts",
            "invoices",
            "quotes",
            "purchase_orders",
            "bills",
            "stock",
            "credit_notes",
            "pay_runs",
            "pay_slips",
        ]
        assert body["sync_in_progress"] is False

    def test_sync_in_progress_reflects_the_shared_cache_lock(self, api: Client) -> None:
        """The flag must read the same lock the worker holds — a worker-local
        flag would show idle while an hour-long run is in flight."""
        _shared.set(SYNC_STATUS_KEY, "task-1")

        assert api.get(SYNC_INFO_URL).json()["sync_in_progress"] is True


def _messages(task_id: str) -> list[dict[str, object]]:
    msgs: list[dict[str, object]] = _shared.get(f"xero_sync_messages_{task_id}", [])
    return msgs


@pytest.mark.django_db
class TestXeroSyncWorker:
    """The worker task's gates and terminal markers.

    Every exit must leave a terminal marker (the SSE stream and monitoring
    read nothing else) and must clear the lock, or the next hourly run is
    refused for the 4-hour lock timeout.
    """

    @override_settings(XERO_READONLY=True)
    def test_readonly_aborts_with_marker_and_clears_the_lock(self) -> None:
        """XERO_READONLY guards E2E/test backends: the run must not push stock
        to Xero or pull tenant data, and must say so rather than fake success."""
        _shared.set(SYNC_STATUS_KEY, "t-readonly")

        xero_sync_task("t-readonly")

        marker = _messages("t-readonly")[-1]
        assert marker["message"] == "Sync skipped: XERO_READONLY is set"
        assert marker["sync_status"] == "aborted"
        assert _shared.get(SYNC_STATUS_KEY) is None

    @override_settings(XERO_READONLY=False)
    def test_sync_disabled_aborts_with_marker(self) -> None:
        """The worker does not read the gate; it reports the engine's refusal.

        The engine raises XeroSyncDisabled, and this branch must treat it like
        the quota floor — an aborted run, no AppError row, no re-raise (the
        task decided correctly, so its TaskResult is SUCCESS)."""
        defaults = CompanyDefaults.get_solo()
        defaults.enable_xero_sync = False
        defaults.save(update_fields=["enable_xero_sync"])
        _shared.set(SYNC_STATUS_KEY, "t-disabled")
        before = AppError.objects.count()

        xero_sync_task("t-disabled")

        marker = _messages("t-disabled")[-1]
        assert marker["sync_status"] == "aborted"
        assert "enable_xero_sync is False" in str(marker["message"])
        assert AppError.objects.count() == before
        assert _shared.get(SYNC_STATUS_KEY) is None

    @override_settings(XERO_READONLY=False)
    def test_progress_renews_the_lock_lease(self) -> None:
        """The lease must mean "four hours since the last progress event": a
        deep sync outliving a fixed lease drops its lock mid-run, and the next
        hourly dispatch then starts a second concurrent sync."""
        _shared.set(SYNC_STATUS_KEY, "t-lease")
        _shared.set("xero_sync_messages_t-lease", [])

        def _events() -> Iterator[dict[str, object]]:
            yield {
                "datetime": "2026-08-15T00:00:00+00:00",
                "entity": "contacts",
                "severity": "info",
                "message": "page 1",
            }
            yield {
                "datetime": "2026-08-15T00:00:01+00:00",
                "entity": "contacts",
                "severity": "info",
                "message": "page 2",
            }

        with (
            patch("apps.xero.sync.synchronise_xero_data", return_value=_events()),
            patch("apps.xero.sync_worker._sync_cache.touch", wraps=_shared.touch) as touch,
        ):
            xero_sync_task("t-lease")

        assert touch.call_args_list == [call(SYNC_STATUS_KEY, LOCK_TIMEOUT)] * 2

    @override_settings(XERO_READONLY=False)
    def test_quota_floor_aborts_without_app_error_and_without_raising(self) -> None:
        """The floor is expected operational signal, not a defect: persisting
        would write 24+ AppError rows a day of noise, and raising would mark
        the TaskResult FAILURE when the task correctly decided to abort."""
        _shared.set(SYNC_STATUS_KEY, "t-quota")
        before = AppError.objects.count()

        with patch(
            "apps.xero.sync.synchronise_xero_data",
            side_effect=XeroQuotaFloorReached("day quota 80 at floor 100"),
        ):
            xero_sync_task("t-quota")  # must not raise

        msgs = _messages("t-quota")
        assert msgs[-1]["sync_status"] == "aborted"
        abort_message = msgs[-2]
        assert "Sync aborted" in str(abort_message["message"])
        assert "error_id" not in abort_message
        assert AppError.objects.count() == before
        assert _shared.get(SYNC_STATUS_KEY) is None

    @override_settings(XERO_READONLY=False)
    def test_generic_error_persists_marks_error_and_raises(self) -> None:
        """A real defect must do all three: an AppError row for the operator,
        an error marker for the stream, and a raise for the FAILURE TaskResult."""
        _shared.set(SYNC_STATUS_KEY, "t-err")
        before = AppError.objects.count()

        with (
            patch(
                "apps.xero.sync.synchronise_xero_data",
                side_effect=RuntimeError("xero exploded"),
            ),
            pytest.raises(RuntimeError),
        ):
            xero_sync_task("t-err")

        assert AppError.objects.count() == before + 1
        app_error = AppError.objects.latest("timestamp")
        msgs = _messages("t-err")
        assert msgs[-1]["sync_status"] == "error"
        assert msgs[-2]["error_id"] == str(app_error.id)
        assert _shared.get(SYNC_STATUS_KEY) is None
