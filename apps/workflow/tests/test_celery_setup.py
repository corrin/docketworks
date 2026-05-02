"""Smoke tests for the Celery setup landed in this PR.

These tests prove the broker URL is configured, the Celery app autodiscovers
the workflow tasks, and a task can be invoked end-to-end. They do not require
a live Redis broker — `CELERY_TASK_ALWAYS_EAGER=True` in settings_test.py runs
the task synchronously in-process.
"""

from django.test import TestCase

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

    def test_health_check_eager(self) -> None:
        """Calling the task via .delay() under TASK_ALWAYS_EAGER returns the
        sentinel — proves the serialize → enqueue → execute pipeline."""
        result = celery_health_check.delay()
        self.assertEqual(result.get(timeout=5), CELERY_HEALTH_CHECK_SENTINEL)
