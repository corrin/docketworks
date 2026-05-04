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

from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import TestCase

from apps.workflow.exceptions import AlreadyLoggedException
from apps.workflow.models import AppError
from apps.workflow.services.xero_sync_service import XeroSyncService
from apps.workflow.tasks import xero_regular_sync_task, xero_sync_task


class XeroSyncTaskFailureTests(TestCase):
    """A failure inside the sync body must persist AppError exactly once
    and surface as AlreadyLoggedException so Celery records FAILURE with
    a populated traceback in TaskResult."""

    def setUp(self):
        cache.delete(XeroSyncService.SYNC_STATUS_KEY)

    def tearDown(self):
        cache.delete(XeroSyncService.SYNC_STATUS_KEY)

    def test_inner_sync_failure_persists_and_raises_already_logged(self):
        task_id = "test-task-failure"
        cache.set(f"xero_sync_messages_{task_id}", [], timeout=60)
        cache.set(XeroSyncService.SYNC_STATUS_KEY, task_id, timeout=60)

        def boom():
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
        # Lock released by the finally block.
        self.assertIsNone(cache.get(XeroSyncService.SYNC_STATUS_KEY))


class XeroRegularSyncSkipTests(TestCase):
    """When start_sync() reports the lock is held (started=False), the Beat
    task must not dispatch xero_sync_task and must return cleanly so its
    own TaskResult is SUCCESS — the sync didn't run, but the *decision*
    succeeded."""

    def setUp(self):
        cache.delete(XeroSyncService.SYNC_STATUS_KEY)

    def tearDown(self):
        cache.delete(XeroSyncService.SYNC_STATUS_KEY)

    def test_lock_held_skips_dispatch_and_returns_cleanly(self):
        # Pre-acquire the lock with some other task_id, simulating a sync
        # that is already running.
        cache.set(
            XeroSyncService.SYNC_STATUS_KEY,
            "other-task-id",
            timeout=60,
        )

        with patch("apps.workflow.tasks.xero_sync_task") as mock_task:
            xero_regular_sync_task()
            mock_task.delay.assert_not_called()
