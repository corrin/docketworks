"""Django app configuration for the core app."""

from django.apps import AppConfig


class CoreConfig(AppConfig):
    """Configure the core application."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.core"
    label = "core"
