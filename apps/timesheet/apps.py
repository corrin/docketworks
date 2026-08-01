"""Django app configuration for apps.timesheet."""

from django.apps import AppConfig


class TimesheetConfig(AppConfig):
    """Registers the timesheet app under its v1-compatible label."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.timesheet"
    label = "timesheet"
