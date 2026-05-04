"""Seed Celery Beat schedule for the seven periodic tasks ported from APScheduler.

Idempotent: re-running the migration leaves the rows untouched. Reverse
migration deletes the rows.
"""

import json

from django.db import migrations

# (task_name, schedule_type, schedule_kwargs, periodic_task_name)
_SCHEDULES = [
    (
        "apps.workflow.tasks.xero_heartbeat_task",
        "interval",
        {"every": 5, "period": "minutes"},
        "xero_heartbeat",
    ),
    (
        "apps.workflow.tasks.xero_regular_sync_task",
        "interval",
        {"every": 1, "period": "hours"},
        "xero_regular_sync",
    ),
    (
        "apps.workflow.tasks.xero_30_day_sync_task",
        "crontab",
        {
            "minute": "0",
            "hour": "2",
            "day_of_week": "6",  # Saturday (cron: 0=Sun, 6=Sat)
            "day_of_month": "*",
            "month_of_year": "*",
            "timezone": "Pacific/Auckland",
        },
        "xero_30_day_sync",
    ),
    (
        "apps.quoting.tasks.run_all_scrapers_task",
        "crontab",
        {
            "minute": "0",
            "hour": "15",
            "day_of_week": "0",  # Sunday
            "day_of_month": "*",
            "month_of_year": "*",
            "timezone": "Pacific/Auckland",
        },
        "run_all_scrapers_weekly",
    ),
    (
        "apps.job.tasks.set_paid_flag_task",
        "crontab",
        {
            "minute": "0",
            "hour": "2",
            "day_of_week": "*",
            "day_of_month": "*",
            "month_of_year": "*",
            "timezone": "Pacific/Auckland",
        },
        "set_paid_flag_jobs",
    ),
    (
        "apps.job.tasks.auto_archive_completed_jobs_task",
        "crontab",
        {
            "minute": "0",
            "hour": "3",
            "day_of_week": "*",
            "day_of_month": "*",
            "month_of_year": "*",
            "timezone": "Pacific/Auckland",
        },
        "auto_archive_completed_jobs",
    ),
    (
        "apps.operations.tasks.recompute_workshop_schedule_task",
        "interval",
        {"every": 1, "period": "hours"},
        "recompute_workshop_schedule",
    ),
]


def seed_schedule(apps, schema_editor):
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    IntervalSchedule = apps.get_model("django_celery_beat", "IntervalSchedule")
    CrontabSchedule = apps.get_model("django_celery_beat", "CrontabSchedule")

    for task_name, schedule_type, schedule_kwargs, periodic_task_name in _SCHEDULES:
        if schedule_type == "interval":
            schedule, _ = IntervalSchedule.objects.get_or_create(**schedule_kwargs)
            PeriodicTask.objects.update_or_create(
                name=periodic_task_name,
                defaults={
                    "task": task_name,
                    "interval": schedule,
                    "crontab": None,
                    "enabled": True,
                    "args": json.dumps([]),
                    "kwargs": json.dumps({}),
                },
            )
        elif schedule_type == "crontab":
            schedule, _ = CrontabSchedule.objects.get_or_create(**schedule_kwargs)
            PeriodicTask.objects.update_or_create(
                name=periodic_task_name,
                defaults={
                    "task": task_name,
                    "crontab": schedule,
                    "interval": None,
                    "enabled": True,
                    "args": json.dumps([]),
                    "kwargs": json.dumps({}),
                },
            )


def remove_schedule(apps, schema_editor):
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    PeriodicTask.objects.filter(
        name__in=[name for _, _, _, name in _SCHEDULES]
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("workflow", "0219_delete_xerotoken"),
        ("django_celery_beat", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_schedule, remove_schedule),
    ]
