"""Django app configuration for the accounts app."""

from django.apps import AppConfig


class AccountsConfig(AppConfig):
    """Registers the accounts app under its v1-parity label."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.accounts"
    label = "accounts"
