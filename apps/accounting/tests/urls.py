"""Test URLconf mounting the accounting router at its production prefix.

config/api.py wires the router into the real API at integration time; the tests
mount their own NinjaAPI so they exercise the exact production paths without
depending on that wiring order (house pattern: apps/job/tests/urls.py).
"""

from django.urls import URLPattern, URLResolver, path
from ninja import NinjaAPI

from apps.accounting.api import router
from apps.core.envelope import register_exception_handlers

api = NinjaAPI(urls_namespace="accounting-tests")
register_exception_handlers(api)
api.add_router("/accounting/", router)

urlpatterns: list[URLPattern | URLResolver] = [
    path("api/", api.urls),
]
