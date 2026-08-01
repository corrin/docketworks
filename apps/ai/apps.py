"""Django app configuration for apps.ai."""

from django.apps import AppConfig


class AiConfig(AppConfig):
    """Registers the ai app under its v1-compatible label."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.ai"
    label = "ai"
