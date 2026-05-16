"""Seed Celery Beat schedule for bounded stock metadata parsing."""

import json

from django.db import migrations

TASK_NAME = "apps.purchasing.tasks.parse_unparsed_stock_items_task"
PERIODIC_TASK_NAME = "parse_unparsed_stock_items_hourly"


def seed_schedule(apps, schema_editor):
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    IntervalSchedule = apps.get_model("django_celery_beat", "IntervalSchedule")

    schedule, _ = IntervalSchedule.objects.get_or_create(every=1, period="hours")
    PeriodicTask.objects.update_or_create(
        name=PERIODIC_TASK_NAME,
        defaults={
            "task": TASK_NAME,
            "interval": schedule,
            "crontab": None,
            "enabled": True,
            "args": json.dumps([]),
            "kwargs": json.dumps({"limit": 50}),
        },
    )


def remove_schedule(apps, schema_editor):
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    PeriodicTask.objects.filter(name=PERIODIC_TASK_NAME).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("workflow", "0225_alter_companydefaults_annual_leave_loading"),
        ("django_celery_beat", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_schedule, remove_schedule),
    ]
