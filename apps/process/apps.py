"""Django app configuration for apps.process."""

from django.apps import AppConfig


class ProcessConfig(AppConfig):
    """Registers the process app under its v1-compatible label."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.process"
    label = "process"
