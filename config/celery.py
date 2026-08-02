"""The Celery app.

Beat schedules live HERE, in code, not in seed migrations (v2 ADR: schedules
must be code-reviewed and env-diffable). Populated as tasks port over.
"""

import os

from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("docketworks")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

app.conf.beat_schedule = {
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
}
