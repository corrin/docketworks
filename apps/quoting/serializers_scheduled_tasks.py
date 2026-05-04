"""Serializers for the read-only Celery Beat schedule + execution views.

Replaces serializers_django_jobs.py — same surface (visibility), backed by
django-celery-beat / django-celery-results models instead of django-apscheduler.
"""

from django_celery_beat.models import PeriodicTask
from django_celery_results.models import TaskResult
from rest_framework import serializers


class ScheduledTaskSerializer(serializers.ModelSerializer):
    """Read-only view over django-celery-beat's PeriodicTask.

    Frontend uses: id, name, task, enabled, last_run_at, schedule.
    Schedule renders as a human string ("every 5 minutes" or cron expr) so the
    UI doesn't need to know about IntervalSchedule vs CrontabSchedule shapes.
    """

    schedule = serializers.SerializerMethodField()

    class Meta:
        model = PeriodicTask
        fields = [
            "id",
            "name",
            "task",
            "enabled",
            "last_run_at",
            "schedule",
        ]

    def get_schedule(self, obj: PeriodicTask) -> str:
        if obj.interval_id:
            return str(obj.interval)
        if obj.crontab_id:
            return str(obj.crontab)
        if obj.solar_id:
            return str(obj.solar)
        if obj.clocked_id:
            return str(obj.clocked)
        return ""


class ScheduledTaskExecutionSerializer(serializers.ModelSerializer):
    """Read-only view over django-celery-results' TaskResult.

    `task_name` here is the dotted Celery task name (e.g.
    apps.workflow.tasks.xero_heartbeat_task). For Beat-scheduled tasks the
    `periodic_task_name` is also populated (the human PeriodicTask.name).
    """

    class Meta:
        model = TaskResult
        fields = [
            "id",
            "task_id",
            "task_name",
            "periodic_task_name",
            "status",
            "date_created",
            "date_started",
            "date_done",
            "result",
            "traceback",
            "worker",
            "task_args",
            "task_kwargs",
        ]
