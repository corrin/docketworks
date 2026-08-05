"""Django app configuration for apps.diagnostics."""

from django.apps import AppConfig


class DiagnosticsConfig(AppConfig):
    """Configure the diagnostics application."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.diagnostics"
    label = "diagnostics"
