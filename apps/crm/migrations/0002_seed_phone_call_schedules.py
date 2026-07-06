"""Seed the Celery Beat schedule for the two phone-call periodic tasks.

Net effect of the pre-squash crm/0001 seed + crm/0005 near-realtime change.
Idempotent (update_or_create keyed by periodic-task name); reverse deletes
the rows.
"""

import json

from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps

SYNC_TASK_NAME = "apps.crm.tasks.sync_phone_calls_task"
DELETE_TASK_NAME = "apps.crm.tasks.delete_archived_phone_recordings_task"
SYNC_PERIODIC_TASK_NAME = "sync_phone_calls_daily"
DELETE_PERIODIC_TASK_NAME = "delete_archived_phone_recordings_daily"


def seed_phone_call_schedules(
    apps: StateApps, schema_editor: BaseDatabaseSchemaEditor
) -> None:
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    CrontabSchedule = apps.get_model("django_celery_beat", "CrontabSchedule")

    sync_schedule, _ = CrontabSchedule.objects.get_or_create(
        minute="*/5",
        hour="*",
        day_of_week="*",
        day_of_month="*",
        month_of_year="*",
        timezone="Pacific/Auckland",
    )
    PeriodicTask.objects.update_or_create(
        name=SYNC_PERIODIC_TASK_NAME,
        defaults={
            "task": SYNC_TASK_NAME,
            "interval": None,
            "crontab": sync_schedule,
            "enabled": True,
            "args": json.dumps([]),
            "kwargs": json.dumps({}),
        },
    )

    delete_schedule, _ = CrontabSchedule.objects.get_or_create(
        minute="45",
        hour="1",
        day_of_week="*",
        day_of_month="*",
        month_of_year="*",
        timezone="Pacific/Auckland",
    )
    PeriodicTask.objects.update_or_create(
        name=DELETE_PERIODIC_TASK_NAME,
        defaults={
            "task": DELETE_TASK_NAME,
            "interval": None,
            "crontab": delete_schedule,
            "enabled": True,
            "args": json.dumps([]),
            "kwargs": json.dumps({"limit": 100}),
        },
    )


def remove_phone_call_schedules(
    apps: StateApps, schema_editor: BaseDatabaseSchemaEditor
) -> None:
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    PeriodicTask.objects.filter(
        name__in=[SYNC_PERIODIC_TASK_NAME, DELETE_PERIODIC_TASK_NAME]
    ).delete()


class Migration(migrations.Migration):
    replaces = [
        ("crm", "0005_phone_call_sync_near_realtime"),
    ]

    dependencies = [
        ("crm", "0001_baseline"),
        ("django_celery_beat", "0016_alter_crontabschedule_timezone"),
    ]

    operations = [
        migrations.RunPython(seed_phone_call_schedules, remove_phone_call_schedules),
    ]
