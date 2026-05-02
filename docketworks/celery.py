"""Celery app for docketworks.

Loaded by `docketworks/__init__.py` on Django startup so `@shared_task`
decorators across `apps/` resolve to this app. Configuration is read from
Django settings under the `CELERY_` namespace (see `docketworks/settings.py`).
"""

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "docketworks.settings")

app = Celery("docketworks")

app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
