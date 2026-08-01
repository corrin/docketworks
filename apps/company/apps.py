"""Django app configuration for apps.company."""

from django.apps import AppConfig


class CompanyConfig(AppConfig):
    """Registers the company app under its v1-compatible label."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.company"
    label = "company"
