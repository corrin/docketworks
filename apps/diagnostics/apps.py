"""Django app configuration for apps.diagnostics."""

from django.apps import AppConfig


class DiagnosticsConfig(AppConfig):
    """Registers the diagnostics app under its v1-compatible label."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.diagnostics"
    label = "diagnostics"
