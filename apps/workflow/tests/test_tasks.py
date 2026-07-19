"""Unit tests for the Xero Celery task pipeline.

xero_sync_task: a failure inside the sync body persists AppError exactly
once and surfaces as AlreadyLoggedException, so Celery records FAILURE
with a populated traceback in TaskResult — the bug PR #273 originally
introduced (a detached thread crash recorded SUCCESS in TaskResult).

xero_regular_sync_task: when start_sync() reports the lock is held
(another sync already in progress), the Beat task body returns cleanly
without dispatching xero_sync_task — its TaskResult stays SUCCESS,
correctly reporting "the dispatch decision succeeded".
"""

from collections.abc import Iterator
from unittest.mock import MagicMock, patch

from django.core.cache import caches
from django.test import override_settings

from apps.testing import BaseTestCase
from apps.workflow.exceptions import (
    AlreadyLoggedException,
    NoValidXeroTokenError,
    XeroQuotaFloorReached,
)
from apps.workflow.models import AppError, CompanyDefaults
from apps.workflow.services.xero_sync_constants import SYNC_STATUS_KEY
from apps.workflow.services.xero_sync_service import (
    XeroSyncService,
    XeroSyncStartResult,
)
from apps.workflow.tasks import (
    xero_30_day_sync_task,
    xero_regular_sync_task,
    xero_sync_task,
)

# Sync state lives on the "shared" alias (Redis in prod, LocMem in tests via
# settings_test). Test fixtures must seed/inspect it on the same alias the
# code under test reads from.
_shared = caches["shared"]


@override_settings(SOLO_CACHE="shared")
class XeroSyncGateCacheTests(BaseTestCase):
    def setUp(self) -> None:
        CompanyDefaults.clear_cache()

    def tearDown(self) -> None:
        CompanyDefaults.clear_cache()

    def test_gate_update_replaces_a_stale_shared_cache_value(self) -> None:
        company = CompanyDefaults.get_solo()
        company.enable_xero_sync = True
        company.save(update_fields=["enable_xero_sync"])

        CompanyDefaults.objects.filter(pk=company.pk).update(enable_xero_sync=False)
        self.assertTrue(CompanyDefaults.get_solo().enable_xero_sync)

        CompanyDefaults.set_xero_sync_enabled(enabled=False)

        cached = _shared.get(CompanyDefaults.get_cache_key())
        self.assertIsNotNone(cached)
        self.assertFalse(cached.enable_xero_sync)
        company.refresh_from_db()
        self.assertFalse(company.enable_xero_sync)


class XeroSyncTaskFailureTests(BaseTestCase):
    """A failure inside the sync body must persist AppError exactly once
    and surface as AlreadyLoggedException so Celery records FAILURE with
    a populated traceback in TaskResult."""

    def setUp(self) -> None:
        _shared.delete(SYNC_STATUS_KEY)
        CompanyDefaults.set_xero_sync_enabled(enabled=True)

    def tearDown(self) -> None:
        _shared.delete(SYNC_STATUS_KEY)

    def test_inner_sync_failure_persists_and_raises_already_logged(self) -> None:
        task_id = "test-task-failure"
        _shared.set(f"xero_sync_messages_{task_id}", [], timeout=60)
        _shared.set(SYNC_STATUS_KEY, task_id, timeout=60)

        def boom() -> Iterator[dict[str, object]]:
            yield {"entity": "contacts", "severity": "info", "message": "starting"}
            raise RuntimeError("xero blew up mid-stream")

        provider = MagicMock()
        provider.run_full_sync.return_value = boom()
        provider.get_sync_entity_count.return_value = 5

        before = AppError.objects.count()
        with patch(
            "apps.workflow.accounting.registry.get_provider",
            return_value=provider,
        ):
            with self.assertRaises(AlreadyLoggedException):
                xero_sync_task(task_id)

        # Exactly one AppError row — no double-persist from a wrapping handler.
        self.assertEqual(AppError.objects.count(), before + 1)
        messages = _shared.get(f"xero_sync_messages_{task_id}", [])
        self.assertEqual(messages[-2]["severity"], "error")
        self.assertEqual(
            messages[-2]["message"], "Error during sync: xero blew up mid-stream"
        )
        self.assertTrue(messages[-2]["error_id"])
        self.assertEqual(messages[-1]["message"], "Sync stream ended")
        self.assertEqual(messages[-1]["sync_status"], "error")
        # Lock released by the finally block.
        self.assertIsNone(_shared.get(SYNC_STATUS_KEY))

    def test_prelogged_sync_failure_surfaces_without_duplicate_app_error(self) -> None:
        task_id = "test-prelogged-failure"
        _shared.set(f"xero_sync_messages_{task_id}", [], timeout=60)
        _shared.set(SYNC_STATUS_KEY, task_id, timeout=60)

        persisted = AppError.objects.create(
            message="No Xero tenants found.",
            app="workflow",
        )

        # `yield from ()` keeps this a generator function — so the error
        # surfaces on iteration, not at call time — without dead code after
        # the raise.
        def boom() -> Iterator[dict[str, object]]:
            yield from ()
            raise AlreadyLoggedException(
                RuntimeError("No Xero tenants found."),
                persisted.id,
            )

        provider = MagicMock()
        provider.run_full_sync.return_value = boom()
        provider.get_sync_entity_count.return_value = 5

        before = AppError.objects.count()
        with patch(
            "apps.workflow.accounting.registry.get_provider",
            return_value=provider,
        ):
            with self.assertRaises(AlreadyLoggedException):
                xero_sync_task(task_id)

        self.assertEqual(AppError.objects.count(), before)
        messages = _shared.get(f"xero_sync_messages_{task_id}", [])
        self.assertEqual(messages[-2]["severity"], "error")
        self.assertEqual(
            messages[-2]["message"], "Error during sync: No Xero tenants found."
        )
        self.assertEqual(messages[-2]["error_id"], str(persisted.id))
        self.assertEqual(messages[-1]["sync_status"], "error")
        self.assertIsNone(_shared.get(SYNC_STATUS_KEY))

    def test_quota_floor_aborts_without_app_error(self) -> None:
        task_id = "test-quota-abort"
        _shared.set(f"xero_sync_messages_{task_id}", [], timeout=60)
        _shared.set(SYNC_STATUS_KEY, task_id, timeout=60)

        def abort() -> Iterator[dict[str, object]]:
            yield from ()
            raise XeroQuotaFloorReached("Skipping sync: Xero day quota at floor (100)")

        provider = MagicMock()
        provider.run_full_sync.return_value = abort()
        provider.get_sync_entity_count.return_value = 5

        before = AppError.objects.count()
        with patch(
            "apps.workflow.accounting.registry.get_provider",
            return_value=provider,
        ):
            xero_sync_task(task_id)

        self.assertEqual(AppError.objects.count(), before)
        messages = _shared.get(f"xero_sync_messages_{task_id}", [])
        self.assertEqual(messages[-2]["severity"], "error")
        self.assertEqual(messages[-1]["sync_status"], "aborted")
        self.assertIsNone(_shared.get(SYNC_STATUS_KEY))

    def test_disabled_gate_skips_queued_worker_before_provider_access(self) -> None:
        task_id = "test-disabled-sync"
        _shared.set(f"xero_sync_messages_{task_id}", [], timeout=60)
        _shared.set(SYNC_STATUS_KEY, task_id, timeout=60)
        CompanyDefaults.set_xero_sync_enabled(enabled=False)

        with patch("apps.workflow.accounting.registry.get_provider") as get_provider:
            xero_sync_task(task_id)

        get_provider.assert_not_called()
        messages = _shared.get(f"xero_sync_messages_{task_id}", [])
        self.assertEqual(messages[-1]["sync_status"], "aborted")
        self.assertIsNone(_shared.get(SYNC_STATUS_KEY))


class XeroSyncStartResultTests(BaseTestCase):
    def setUp(self) -> None:
        _shared.delete(SYNC_STATUS_KEY)
        CompanyDefaults.set_xero_sync_enabled(enabled=True)

    def tearDown(self) -> None:
        _shared.delete(SYNC_STATUS_KEY)

    def test_start_sync_reports_already_running_without_exception(self) -> None:
        _shared.set(SYNC_STATUS_KEY, "existing-task", timeout=60)

        result = XeroSyncService.start_sync()

        self.assertEqual(
            result,
            XeroSyncStartResult(
                started=False,
                reason="already_running",
                task_id="existing-task",
            ),
        )

    def test_start_sync_reports_no_valid_token_without_exception(self) -> None:
        provider = MagicMock()
        provider.get_valid_token.return_value = None

        with patch(
            "apps.workflow.services.xero_sync_service.get_provider",
            return_value=provider,
        ):
            result = XeroSyncService.start_sync()

        self.assertEqual(result.started, False)
        self.assertEqual(result.reason, "no_valid_token")
        self.assertIsNone(result.task_id)
        self.assertIsNone(_shared.get(SYNC_STATUS_KEY))

    def test_start_sync_releases_lock_when_token_refresh_raises(self) -> None:
        provider = MagicMock()
        provider.get_valid_token.side_effect = AlreadyLoggedException(
            RuntimeError("refresh failed"),
            "app-error-id",
        )

        with patch(
            "apps.workflow.services.xero_sync_service.get_provider",
            return_value=provider,
        ):
            with self.assertRaises(AlreadyLoggedException):
                XeroSyncService.start_sync()

        self.assertIsNone(_shared.get(SYNC_STATUS_KEY))

    def test_start_sync_reports_started_task_id(self) -> None:
        provider = MagicMock()
        provider.get_valid_token.return_value = {"access_token": "token"}

        with (
            patch(
                "apps.workflow.services.xero_sync_service.get_provider",
                return_value=provider,
            ),
            patch(
                "apps.workflow.services.xero_sync_service.xero_sync_task.delay"
            ) as delay,
        ):
            result = XeroSyncService.start_sync()

        self.assertTrue(result.started)
        self.assertEqual(result.reason, "started")
        self.assertTrue(result.task_id)
        delay.assert_called_once_with(result.task_id)

    def test_sync_all_xero_data_raises_when_token_missing(self) -> None:
        from apps.workflow.api.xero.sync import sync_all_xero_data

        with patch("apps.workflow.api.xero.sync.get_valid_token", return_value=None):
            with self.assertRaises(NoValidXeroTokenError):
                list(sync_all_xero_data())


@override_settings(SOLO_CACHE="shared")
class XeroRegularSyncSkipTests(BaseTestCase):
    """When start_sync() reports the lock is held (started=False), the Beat
    task must not dispatch xero_sync_task and must return cleanly so its
    own TaskResult is SUCCESS — the sync didn't run, but the *decision*
    succeeded."""

    def setUp(self) -> None:
        _shared.delete(SYNC_STATUS_KEY)
        CompanyDefaults.set_xero_sync_enabled(enabled=True)

    def tearDown(self) -> None:
        _shared.delete(SYNC_STATUS_KEY)
        CompanyDefaults.clear_cache()

    def test_lock_held_skips_dispatch_and_returns_cleanly(self) -> None:
        # Pre-acquire the lock with some other task_id, simulating a sync
        # that is already running.
        _shared.set(
            SYNC_STATUS_KEY,
            "other-task-id",
            timeout=60,
        )

        with (
            patch("apps.workflow.tasks.close_old_connections"),
            patch("apps.workflow.tasks.xero_sync_task") as mock_task,
        ):
            xero_regular_sync_task()
            mock_task.delay.assert_not_called()

    def test_disabled_gate_skips_all_periodic_sync_dispatch(self) -> None:
        CompanyDefaults.set_xero_sync_enabled(enabled=False)

        with (
            patch("apps.workflow.tasks.close_old_connections"),
            patch.object(XeroSyncService, "start_sync") as start_sync,
        ):
            xero_regular_sync_task()
            xero_30_day_sync_task()

        start_sync.assert_not_called()

    def test_disabled_gate_stops_before_quota_and_pay_item_calls(self) -> None:
        from apps.workflow.api.xero.sync import synchronise_xero_data

        CompanyDefaults.set_xero_sync_enabled(enabled=False)

        with (
            patch("apps.workflow.api.xero.sync.quota_floor_breached") as quota,
            patch(
                "apps.workflow.api.xero.payroll.sync_xero_pay_items"
            ) as sync_pay_items,
        ):
            messages = list(synchronise_xero_data())

        quota.assert_not_called()
        sync_pay_items.assert_not_called()
        self.assertEqual(messages[-1]["severity"], "warning")
