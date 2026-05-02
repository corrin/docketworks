"""Celery tasks for the workflow app.

PR 1 only contains the smoke-test task that proves the broker/worker pipeline
works end-to-end. The Xero webhook task lands in PR 2 (Trello card #291).
"""

from celery import shared_task

CELERY_HEALTH_CHECK_SENTINEL = "docketworks-celery-ok"


@shared_task(name="apps.workflow.tasks.celery_health_check")
def celery_health_check() -> str:
    """Return a deterministic sentinel — proof the broker, worker, and task
    autodiscovery are all wired up. Used in unit tests and in the deploy
    runbook for a manual round-trip check."""
    return CELERY_HEALTH_CHECK_SENTINEL
