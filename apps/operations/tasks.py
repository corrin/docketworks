"""Celery tasks for the operations application.

Task names are an operational contract because callers reference them by
string. This one is dispatched by ``push.schedule_data_versions_publish``, not
by Beat, and carries the trailing edge of the publish coalescing window.
"""

import logging

from celery import shared_task
from django.db import close_old_connections, connection

from apps.operations.push import publish_trailing_data_versions

logger = logging.getLogger("apps.operations.tasks")


@shared_task(name="apps.operations.tasks.publish_data_versions_task")
def publish_data_versions_task() -> None:
    """Push the settled data versions after a write burst.

    Idempotent by construction: it reads the current versions and pushes them,
    so a duplicate delivery publishes the same document. Deduplication is the
    dispatcher's shared-cache lease, which this task releases before it reads
    (``publish_trailing_data_versions``) — which is what lets celery's
    at-least-once delivery be correct rather than merely tolerated (ADR 0024).
    """
    # Eager mode runs inside the request's transaction; closing the connection
    # there would kill it (same guard as apps/job/tasks.py).
    if not connection.in_atomic_block:
        close_old_connections()
    publish_trailing_data_versions()
