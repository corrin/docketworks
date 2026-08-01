"""Django app configuration for apps.operations."""

from django.apps import AppConfig


class OperationsConfig(AppConfig):
    """Registers the operations app under its v1-compatible label."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.operations"
    label = "operations"
