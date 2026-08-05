"""Django app configuration for apps.purchasing."""

from django.apps import AppConfig


class PurchasingConfig(AppConfig):
    """Configure the purchasing application."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.purchasing"
    label = "purchasing"
