import json

from django.db import migrations

TASK_NAME = "apps.workflow.tasks.purge_old_session_replays_task"
PERIODIC_TASK_NAME = "purge_old_session_replays_daily"


def seed_schedule(apps, schema_editor):
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    CrontabSchedule = apps.get_model("django_celery_beat", "CrontabSchedule")

    schedule, _ = CrontabSchedule.objects.get_or_create(
        minute="30",
        hour="1",
        day_of_week="*",
        day_of_month="*",
        month_of_year="*",
        timezone="Pacific/Auckland",
    )
    PeriodicTask.objects.update_or_create(
        name=PERIODIC_TASK_NAME,
        defaults={
            "task": TASK_NAME,
            "interval": None,
            "crontab": schedule,
            "enabled": True,
            "args": json.dumps([]),
            "kwargs": json.dumps({}),
        },
    )


def remove_schedule(apps, schema_editor):
    PeriodicTask = apps.get_model("django_celery_beat", "PeriodicTask")
    PeriodicTask.objects.filter(name=PERIODIC_TASK_NAME).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("workflow", "0228_session_replay"),
        ("django_celery_beat", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_schedule, remove_schedule),
    ]
