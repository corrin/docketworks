"""Django app configuration for apps.accounting."""

from django.apps import AppConfig


class AccountingConfig(AppConfig):
    """Configure the accounting application."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.accounting"
    label = "accounting"
