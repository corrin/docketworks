"""Root URL routing: the Django admin plus the single NinjaAPI under /api/."""

from django.contrib import admin
from django.urls import path

from config.api import api

urlpatterns = [
    path("django-admin/", admin.site.urls),
    path("api/", api.urls),
]
