"""Django app configuration for apps.search."""

from django.apps import AppConfig


class SearchConfig(AppConfig):
    """Registers the search app under its v1-compatible label."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.search"
    label = "search"
