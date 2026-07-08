"""Seed the Celery Beat schedule for the nine periodic tasks.

Net effect of the pre-squash workflow/0220 + 0226 + 0229 seeds. Idempotent
(update_or_create keyed by periodic-task name); reverse deletes the rows.
"""

import json

from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps

# (task_path, schedule_type, schedule_kwargs, periodic_task_name, task_kwargs)
_SCHEDULES: list[tuple[str, str, dict[str, str | int], str, dict[str, int]]] = [
    (
        "apps.workflow.tasks.xero_heartbeat_task",
        "interval",
        {"every": 5, "period": "minutes"},
        "xero_heartbeat",
        {},
    ),
    (
        "apps.workflow.tasks.xero_regular_sync_task",
        "interval",
        {"every": 1, "period": "hours"},
        "xero_regular_sync",
        {},
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
        {},
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
        {},
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
        {},
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
        {},
    ),
    (
        "apps.operations.tasks.recompute_workshop_schedule_task",
        "interval",
        {"every": 1, "period": "hours"},
        "recompute_workshop_schedule",
        {},
    ),
    (
        "apps.purchasing.tasks.parse_unparsed_stock_items_task",
        "interval",
        {"every": 1, "period": "hours"},
        "parse_unparsed_stock_items_hourly",
        {"limit": 50},
    ),
    (
        "apps.workflow.tasks.purge_old_session_replays_task",
        "crontab",
        {
            "minute": "30",
            "hour": "1",
            "day_of_week": "*",
            "day_of_month": "*",
            "month_of_year": "*",
            "timezone": "Pacific/Auckland",
        },
        "purge_old_session_replays_daily",
        {},
    ),
]


def seed_schedules(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    IntervalSchedule = apps.get_model("django_celery_beat", "IntervalSchedule")
    CrontabSchedule = apps.get_model("django_celery_beat", "CrontabSchedule")

    for task_path, schedule_type, schedule_kwargs, name, task_kwargs in _SCHEDULES:
        if schedule_type == "interval":
            schedule, _ = IntervalSchedule.objects.get_or_create(**schedule_kwargs)
            defaults = {"interval": schedule, "crontab": None}
        else:
            schedule, _ = CrontabSchedule.objects.get_or_create(**schedule_kwargs)
            defaults = {"interval": None, "crontab": schedule}
        PeriodicTask.objects.update_or_create(
            name=name,
            defaults={
                **defaults,
                "task": task_path,
                "enabled": True,
                "args": json.dumps([]),
                "kwargs": json.dumps(task_kwargs),
            },
        )


def remove_schedules(apps: StateApps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    PeriodicTask.objects.filter(
        name__in=[name for _, _, _, name, _ in _SCHEDULES]
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("workflow", "0002_seed_xero_pay_items"),
        # CrontabSchedule.timezone (used in _SCHEDULES) only exists from
        # django_celery_beat 0006; depend on the migration that last touches
        # it so fresh-DB migration order is always valid.
        ("django_celery_beat", "0016_alter_crontabschedule_timezone"),
    ]

    operations = [
        migrations.RunPython(seed_schedules, remove_schedules),
    ]
