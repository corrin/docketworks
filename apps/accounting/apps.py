"""Django app configuration for apps.accounting."""

from django.apps import AppConfig


class AccountingConfig(AppConfig):
    """Registers the accounting app under its v1-compatible label."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.accounting"
    label = "accounting"
