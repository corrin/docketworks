"""The Celery app.

Beat schedules live here, in code, not in seed migrations. They must be
code-reviewed and environment-diffable.

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
        # Still pending from v1's workflow/0003 seed: recompute_workshop_schedule
        # (hourly there). It cannot be scheduled yet — v2 has no scheduling
        # algorithm at all; apps/operations carries only the schema-shell models
        # (docs/rewrite-status.md, "Operations"). Add the entry with the
        # algorithm port, never before: a beat entry naming an unregistered
        # task dispatches nothing, silently.
        # CRM task names are operational contracts. The "daily" sync name is
        # historical; it runs 5-minutely. Crontabs use Pacific/Auckland time.
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
        # Xero (v1 workflow/0003 seed): token heartbeat 5-minutely; the
        # hourly sync dispatches via XeroSyncService (lock + worker task);
        # Saturday 02:00 NZT gives the 30/90-day deep-sync window its chance
        # (the decision itself lives in synchronise_xero_data).
        # v1 seeded the regular sync as an every-1-hour *interval*, which fires
        # relative to whenever beat last started. minute=15 is deliberate, not
        # drift: a fixed minute survives beat restarts without walking around
        # the clock and stays clear of the on-the-hour daily jobs below.
        "xero_heartbeat_task": {
            "task": "apps.xero.tasks.xero_heartbeat_task",
            "schedule": crontab(minute="*/5"),
        },
        "xero_regular_sync_task": {
            "task": "apps.xero.tasks.xero_regular_sync_task",
            "schedule": crontab(minute="15"),
        },
        "xero_30_day_sync_task": {
            "task": "apps.xero.tasks.xero_30_day_sync_task",
            "schedule": crontab(minute="0", hour="2", day_of_week="6"),
        },
        # workflow/0003 seed: hourly catch-up parse for active stock rows still
        # missing metadata (the write-site enqueue covers new rows; this sweeps
        # anything that predates it or whose parse errored). v1 used an
        # every-1-hour interval; minute=30 is the same deliberate fixed-minute
        # adaptation as xero_regular_sync above, offset from it so the two
        # hourly tasks never contend for the same beat tick.
        "parse_unparsed_stock_items_hourly": {
            "task": "apps.purchasing.tasks.parse_unparsed_stock_items_task",
            "schedule": crontab(minute="30"),
            "kwargs": {"limit": 50},
        },
        # workflow/0003 seed: daily replay purge at 01:30 NZT, before the 02:00
        # and 03:00 job-maintenance tasks. Retention lives beside the task
        # (apps/diagnostics/tasks.py) — see there for the v1 disk-store
        # adaptation.
        "purge_old_session_replays_daily": {
            "task": "apps.diagnostics.tasks.purge_old_session_replays_task",
            "schedule": crontab(minute="30", hour="1"),
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
