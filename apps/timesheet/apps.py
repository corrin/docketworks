"""Django app configuration for apps.timesheet."""

from django.apps import AppConfig


class TimesheetConfig(AppConfig):
    """Configure the timesheet application."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.timesheet"
    label = "timesheet"
