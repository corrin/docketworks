"""Celery app. Beat schedules live HERE, in code, not in seed migrations (v2 ADR:
schedules must be code-reviewed and env-diffable). Populated as tasks port over."""

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("docketworks")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

app.conf.beat_schedule = {
    # Ported from v1's seed migrations (workflow/0003, crm/0002) as each task lands.
}
