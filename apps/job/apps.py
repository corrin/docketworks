"""Django app configuration for apps.job."""

from django.apps import AppConfig


class JobConfig(AppConfig):
    """Registers the job app under its v1-compatible label."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.job"
    label = "job"
