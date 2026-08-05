"""Django app configuration for apps.operations."""

from django.apps import AppConfig


class OperationsConfig(AppConfig):
    """Configure the operations application."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.operations"
    label = "operations"
