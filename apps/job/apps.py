"""Django app configuration for apps.job."""

from django.apps import AppConfig


class JobConfig(AppConfig):
    """Configure the job application."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.job"
    label = "job"
