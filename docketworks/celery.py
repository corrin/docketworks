"""Celery app for docketworks.

Loaded by `docketworks/__init__.py` on Django startup so `@shared_task`
decorators across `apps/` resolve to this app. Configuration is read from
Django settings under the `CELERY_` namespace (see `docketworks/settings.py`).
"""

import logging
import os

from celery import Celery
from celery.signals import task_unknown

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "docketworks.settings")

app = Celery("docketworks")

app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

logger = logging.getLogger("celery")


@task_unknown.connect
def _persist_unknown_task(sender=None, name=None, id=None, message=None, **_):
    """Make Celery's silent ack-discard of unregistered tasks loud.

    By default a worker that receives a message for a task it doesn't know
    logs a warning and ACKs the message — the work is gone with no signal
    to anyone. The classic trigger is a deploy that restarts gunicorn
    before the worker, so new task names dispatch into a still-stale
    worker. We hit this on dev during the webhook-Celery rollout.

    Persisting an AppError per ADR 0019 surfaces this in the grouped-
    error view immediately. Imported lazily so this module stays
    importable when Django apps haven't initialised yet (Celery loads
    very early).
    """
    logger.error(
        "Celery received message for unregistered task %r (id=%s). "
        "Likely cause: worker has stale code (deploy ordering issue). "
        "Message dropped.",
        name,
        id,
    )
    try:
        from apps.workflow.services.error_persistence import persist_app_error

        persist_app_error(
            RuntimeError(f"Celery worker received unregistered task: {name}"),
            additional_context={
                "task_name": name,
                "task_id": id,
                "delivery_tag": getattr(message, "delivery_tag", None),
            },
        )
    except Exception:
        # AppError persistence may itself fail (DB down, app registry not
        # ready). Don't crash the worker on top of an already-bad signal.
        logger.exception("Failed to persist AppError for unknown-task signal")
