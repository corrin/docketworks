"""Django app configuration for apps.crm."""

from django.apps import AppConfig


class CrmConfig(AppConfig):
    """Registers the crm app under its v1-compatible label."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.crm"
    label = "crm"
