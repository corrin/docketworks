"""Django app configuration for apps.xero."""

from django.apps import AppConfig


class XeroConfig(AppConfig):
    """Configure the Xero application."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.xero"
    label = "xero"

    def ready(self) -> None:
        """Register the Xero providers with the accounting registry.

        This is the inversion ADR 0012 relies on: the domain layer resolves
        providers by name and never imports this app; this app pushes its
        implementations down at boot.
        """
        from apps.accounting.registry import register_provider  # noqa: PLC0415
        from apps.xero.provider import XeroAccountingProvider  # noqa: PLC0415
        from apps.xero.readonly_provider import XeroReadOnlyProvider  # noqa: PLC0415

        register_provider("xero", XeroAccountingProvider)
        register_provider("xero_readonly", XeroReadOnlyProvider)
