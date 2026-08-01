"""Django app configuration for apps.xero."""

from django.apps import AppConfig


class XeroConfig(AppConfig):
    """Registers the xero app under its v1-compatible label."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.xero"
    label = "xero"
