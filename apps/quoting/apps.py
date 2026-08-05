"""Django app configuration for apps.quoting."""

from django.apps import AppConfig


class QuotingConfig(AppConfig):
    """Configure the quoting application."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.quoting"
    label = "quoting"
