"""Django app configuration for the core app."""

from django.apps import AppConfig


class CoreConfig(AppConfig):
    """Registers the core app under its v1-parity label."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.core"
    label = "core"
