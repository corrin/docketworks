"""Root URL routing: the single NinjaAPI under /api/ (no Django admin, as v1)."""

from django.urls import path

from config.api import api

urlpatterns = [
    path("api/", api.urls),
]
