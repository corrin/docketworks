import json

from django.db import migrations
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.state import StateApps

SYNC_TASK_NAME = "apps.crm.tasks.sync_phone_calls_task"
SYNC_PERIODIC_TASK_NAME = "sync_phone_calls_daily"


def set_near_realtime_phone_call_schedule(
    apps: StateApps, schema_editor: BaseDatabaseSchemaEditor
) -> None:
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    CrontabSchedule = apps.get_model("django_celery_beat", "CrontabSchedule")

    schedule, _ = CrontabSchedule.objects.get_or_create(
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
            "crontab": schedule,
            "enabled": True,
            "args": json.dumps([]),
            "kwargs": json.dumps({}),
        },
    )


def restore_daily_phone_call_schedule(
    apps: StateApps, schema_editor: BaseDatabaseSchemaEditor
) -> None:
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    CrontabSchedule = apps.get_model("django_celery_beat", "CrontabSchedule")

    schedule, _ = CrontabSchedule.objects.get_or_create(
        minute="15",
        hour="1",
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
            "crontab": schedule,
            "enabled": True,
            "args": json.dumps([]),
            "kwargs": json.dumps({}),
        },
    )


class Migration(migrations.Migration):
    dependencies = [
        ("crm", "0004_phonecallrecord_job_link"),
        ("django_celery_beat", "0016_alter_crontabschedule_timezone"),
    ]

    operations = [
        migrations.RunPython(
            set_near_realtime_phone_call_schedule,
            restore_daily_phone_call_schedule,
        ),
    ]
