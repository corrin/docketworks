"""Django app configuration for apps.process."""

from django.apps import AppConfig


class ProcessConfig(AppConfig):
    """Configure the process application."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.process"
    label = "process"
