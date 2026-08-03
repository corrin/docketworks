"""The Celery app.

Beat schedules live HERE, in code, not in seed migrations (v2 ADR: schedules
must be code-reviewed and env-diffable). Populated as tasks port over.

Every entry is stamped with a ``periodic_task_name`` message header by
``_with_periodic_task_headers`` below — see that function for why.
"""

import os
from typing import Any

from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("docketworks")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()


def _with_periodic_task_headers(schedule: dict[str, Any]) -> dict[str, Any]:
    """Stamp each beat entry with its own name as a ``periodic_task_name`` header.

    ``django_celery_results`` records a task execution's originating schedule by
    reading ``request.periodic_task_name`` (``backends/database.py``), which
    Celery populates from a message header. ``django_celery_beat`` sets that
    header for you; a plain in-code ``beat_schedule`` does not. Without it every
    execution is stored with a NULL ``periodic_task_name``, and the scheduled-task
    endpoints — which look executions up by exactly that column — report every
    task as having never run.

    Stamping is derived here rather than written out per entry so that adding a
    schedule cannot silently forget it. ``config/tests/test_celery_beat.py``
    asserts the invariant holds for every entry.
    """
    return {
        name: {
            **entry,
            "options": {**entry.get("options", {}), "headers": {"periodic_task_name": name}},
        }
        for name, entry in schedule.items()
    }


app.conf.beat_schedule = _with_periodic_task_headers(
    {
        # Ported from v1's seed migrations as each task lands (workflow/0003 pending).
        # crm/0002 (names kept from v1; the "daily" sync name is historical — it
        # runs 5-minutely; crontabs evaluate in CELERY_TIMEZONE = Pacific/Auckland):
        "sync_phone_calls_daily": {
            "task": "apps.crm.tasks.sync_phone_calls_task",
            "schedule": crontab(minute="*/5"),
        },
        "delete_archived_phone_recordings_daily": {
            "task": "apps.crm.tasks.delete_archived_phone_recordings_task",
            "schedule": crontab(minute="45", hour="1"),
            "kwargs": {"limit": 100},
        },
        # workflow/0003 seed (restored in Phase 3b-3 with the paid-flag and
        # auto-archive services). Archive runs one hour after the paid flag so
        # freshly paid jobs become archive-eligible; NZT via CELERY_TIMEZONE.
        "set_paid_flag_daily": {
            "task": "apps.job.tasks.set_paid_flag_task",
            "schedule": crontab(minute="0", hour="2"),
        },
        "auto_archive_completed_jobs_daily": {
            "task": "apps.job.tasks.auto_archive_completed_jobs_task",
            "schedule": crontab(minute="0", hour="3"),
        },
        # workflow/0003 seed: the weekly supplier-price scrape, Sunday 15:00 NZT.
        # Sunday afternoon because a full Steel & Tube run is hours of browser work
        # against their portal and must land before Monday's quoting.
        "run_all_scrapers_weekly": {
            "task": "apps.quoting.tasks.run_all_scrapers_task",
            "schedule": crontab(minute="0", hour="15", day_of_week="0"),
        },
    }
)
