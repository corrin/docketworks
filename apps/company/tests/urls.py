"""Test URLconf mounting the company router at its production prefixes.

config/api.py wires the router into the real API at integration time; the
tests mount their own NinjaAPI (ninja allows one router on multiple API
instances) so they exercise the exact production paths without depending on
that wiring order.
"""

from django.urls import URLPattern, URLResolver, path
from ninja import NinjaAPI

from apps.company.api import router
from apps.core.envelope import register_exception_handlers

api = NinjaAPI(urls_namespace="company-tests")
register_exception_handlers(api)
api.add_router("/", router)

urlpatterns: list[URLPattern | URLResolver] = [
    path("api/", api.urls),
]
