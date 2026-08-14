"""Django app configuration for apps.operations."""

from django.apps import AppConfig


class OperationsConfig(AppConfig):
    """Configure the operations application."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.operations"
    label = "operations"

    def ready(self) -> None:
        """Wire the data-version push signals and the core observer seam."""
        # Deferred: push.py imports models from six apps, which the registry
        # cannot resolve at module-import time.
        from apps.operations.push import connect_data_version_signals  # noqa: PLC0415

        connect_data_version_signals()
