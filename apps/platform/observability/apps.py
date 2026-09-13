"""Django registration for platform observability."""

from django.apps import AppConfig


class ObservabilityConfig(AppConfig):
    """Own the record of what the install spends on external vendors."""

    name = "apps.platform.observability"
    label = "observability"
    default_auto_field = "django.db.models.BigAutoField"
