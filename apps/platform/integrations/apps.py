"""Django registration for install-level integrations."""

from django.apps import AppConfig


class IntegrationsConfig(AppConfig):
    """Own integration settings independently of business apps."""

    name = "apps.platform.integrations"
    label = "integrations"
    default_auto_field = "django.db.models.BigAutoField"
