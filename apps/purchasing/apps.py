"""Django app configuration for apps.purchasing."""

from django.apps import AppConfig


class PurchasingConfig(AppConfig):
    """Registers the purchasing app under its v1-compatible label."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.purchasing"
    label = "purchasing"
