"""Django app configuration for apps.quoting."""

from django.apps import AppConfig


class QuotingConfig(AppConfig):
    """Registers the quoting app under its v1-compatible label."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.quoting"
    label = "quoting"
