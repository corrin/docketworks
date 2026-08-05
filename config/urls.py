"""Root URL routing for the single Ninja API under ``/api/``."""

from django.urls import path

from config.api import api

urlpatterns = [
    path("api/", api.urls),
]
