"""Django app configuration for apps.crm."""

from django.apps import AppConfig


class CrmConfig(AppConfig):
    """Configure the CRM application."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.crm"
    label = "crm"
