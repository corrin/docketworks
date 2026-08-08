"""Django app configuration for the core app."""

from importlib import import_module

from django.apps import AppConfig


class CoreConfig(AppConfig):
    """Configure the core application."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.core"
    label = "core"

    def ready(self) -> None:
        """Register checks that require fully loaded model classes."""
        # Importing checks at module load would import CompanyDefaults before
        # Django finishes populating the model registry; ready() is the first
        # lifecycle point where that dependency is valid.
        import_module("apps.core.checks")
