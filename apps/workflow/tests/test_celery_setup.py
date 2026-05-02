"""Smoke tests for the Celery setup landed in this PR.

These tests prove the broker URL is configured, the Celery app autodiscovers
the workflow tasks, and a task can be invoked end-to-end. They do not require
a live Redis broker — `CELERY_TASK_ALWAYS_EAGER=True` in settings_test.py runs
the task synchronously in-process.
"""

from types import SimpleNamespace

from celery.signals import task_unknown
from django.test import TestCase

from apps.workflow.models import AppError
from apps.workflow.tasks import (
    CELERY_HEALTH_CHECK_SENTINEL,
    celery_health_check,
)
from docketworks.celery import app as celery_app


class CelerySetupTests(TestCase):
    def test_celery_app_imports(self) -> None:
        """The Celery app loads with the expected name."""
        self.assertEqual(celery_app.main, "docketworks")

    def test_broker_config_present(self) -> None:
        """The broker URL is set and points at Redis db 1 (channels uses db 0)."""
        broker_url = celery_app.conf.broker_url
        self.assertTrue(broker_url, "CELERY_BROKER_URL must be set")
        self.assertTrue(
            broker_url.startswith("redis://"),
            f"Expected redis broker, got {broker_url!r}",
        )
        self.assertTrue(
            broker_url.endswith("/1"),
            f"Expected db 1 (channels uses db 0), got {broker_url!r}",
        )

    def test_health_check_task_registered(self) -> None:
        """Autodiscovery picked up apps.workflow.tasks."""
        self.assertIn(
            "apps.workflow.tasks.celery_health_check",
            celery_app.tasks,
        )

    def test_health_check_apply(self) -> None:
        """Run the task synchronously via .apply() — exercises the Celery
        machinery (registration, signature, return value) without touching
        the broker. .apply() is broker-free regardless of eager-mode settings,
        so this works under any DJANGO_SETTINGS_MODULE."""
        result = celery_health_check.apply()
        self.assertEqual(result.get(), CELERY_HEALTH_CHECK_SENTINEL)


class UnknownTaskSignalTests(TestCase):
    """The task_unknown signal handler must persist an AppError so that a
    stale worker silently ack-discarding messages becomes visible instead
    of vanishing into the logs. Triggered by deploys that restart gunicorn
    before celery — the new task name dispatches into a worker that
    doesn't know about it."""

    def test_unknown_task_signal_persists_app_error(self) -> None:
        before = AppError.objects.count()
        message = SimpleNamespace(delivery_tag="unit-test-delivery-tag")
        # Send the same signal Celery emits internally when a worker
        # consumes a message naming a task that isn't in its registry.
        task_unknown.send(
            sender=celery_app,
            name="apps.workflow.tasks.does_not_exist",
            id="unit-test-task-id",
            message=message,
        )
        self.assertEqual(AppError.objects.count(), before + 1)
        err = AppError.objects.latest("timestamp")
        self.assertIn("unregistered task", err.message)
        self.assertIn("apps.workflow.tasks.does_not_exist", err.message)
        # persist_app_error merges additional_context into the data dict
        # (alongside the traceback), it doesn't nest it.
        self.assertEqual(err.data["task_name"], "apps.workflow.tasks.does_not_exist")
        self.assertEqual(err.data["task_id"], "unit-test-task-id")
        self.assertEqual(err.data["delivery_tag"], "unit-test-delivery-tag")
