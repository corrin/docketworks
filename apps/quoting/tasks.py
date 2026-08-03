"""Celery tasks for the quoting app, ported from v1 ``apps/quoting/tasks.py``.

Task names are part of the operational contract (beat schedule entries name
them) and are identical to v1's.

Beat wiring (``config/celery.py``, not here): v1 seeded ``run_all_scrapers_task``
for Sunday 15:00 NZT. That entry is NOT yet in v2's in-code schedule — adding it
is reported with this slice rather than applied, because the task's Selenium
scrapers are themselves unported (see ``apps/quoting/scrapers/base.py``), so
scheduling it today would only produce a weekly no-op.
"""

import logging

from celery import shared_task
from django.core.management import call_command
from django.db import close_old_connections

from apps.core.errors import persist_app_error

scheduler_logger = logging.getLogger("apps.quoting.tasks")


@shared_task(name="apps.quoting.tasks.run_all_scrapers_task")
def run_all_scrapers_task() -> None:
    """Run every configured supplier-price scraper (beat-scheduled, weekly).

    Delegates to the ``run_scrapers`` management command with ``--refresh-old``
    so existing products are re-priced, not just newly listed ones.
    """
    scheduler_logger.info("Running run_all_scrapers_task.")
    try:
        close_old_connections()
        call_command("run_scrapers", refresh_old=True)
        scheduler_logger.info("Successfully completed scheduled scraper run.")
    except Exception as exc:
        scheduler_logger.exception("Error during scheduled scraper run.")
        persist_app_error(exc)
        raise
