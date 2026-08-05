"""Django app configuration for apps.company."""

from django.apps import AppConfig


class CompanyConfig(AppConfig):
    """Configure the company application."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.company"
    label = "company"
