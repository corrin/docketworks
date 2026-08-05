"""Django app configuration for apps.search."""

from django.apps import AppConfig


class SearchConfig(AppConfig):
    """Configure the search application."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.search"
    label = "search"
