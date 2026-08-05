"""Django app configuration for apps.xero."""

from django.apps import AppConfig


class XeroConfig(AppConfig):
    """Configure the Xero application."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.xero"
    label = "xero"
