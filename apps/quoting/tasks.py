"""Celery tasks for the quoting application.

Task names are part of the operational contract (beat schedule entries name
them) and are identical to v1's.

Beat wiring lives in ``config/celery.py``, not here: ``run_all_scrapers_weekly``
runs this task at Sunday 15:00 Pacific/Auckland, matching v1's workflow/0003 seed.
"""

import logging

from celery import shared_task
from django.core.management import call_command
from django.db import close_old_connections, connection

from apps.core.errors import AppErrorContext, persist_app_error

scheduler_logger = logging.getLogger("apps.quoting.tasks")


def _connection_hygiene() -> None:
    """Recycle stale connections, except when a caller's transaction owns ours.

    Same guard as ``apps.purchasing.tasks`` and ``apps.job.tasks``: a task
    executed eagerly inside a request or a test runs in the caller's atomic
    block, and closing connections there drops the caller's own. Unguarded
    ``close_old_connections()`` here did exactly that.

    NOTE (ADR 0039): this is the fourth copy of one concept in the codebase —
    ``apps.job.tasks`` inlines it four times, ``apps.purchasing.tasks``
    extracts it, ``apps.crm.tasks`` still calls the unguarded form. One home in
    ``apps.core`` is the fix; it spans three merged slices, so it is reported
    rather than done here.
    """
    if not connection.in_atomic_block:
        close_old_connections()


@shared_task(name="apps.quoting.tasks.run_all_scrapers_task")
def run_all_scrapers_task() -> None:
    """Run every configured supplier-price scraper (beat-scheduled, weekly).

    Delegates to the ``run_scrapers`` management command with ``--refresh-old``
    so existing products are re-priced, not just newly listed ones.
    """
    scheduler_logger.info("Running run_all_scrapers_task.")
    try:
        _connection_hygiene()
        call_command("run_scrapers", refresh_old=True)
        scheduler_logger.info("Successfully completed scheduled scraper run.")
    except Exception as exc:
        scheduler_logger.exception("Error during scheduled scraper run.")
        persist_app_error(
            exc, AppErrorContext(additional_context={"task": "run_all_scrapers_task"})
        )
        raise
