"""Django app configuration for apps.ai."""

from django.apps import AppConfig


class AiConfig(AppConfig):
    """Configure the AI application."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.ai"
    label = "ai"
