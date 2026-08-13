"""Test URLconf mounting the accounts router at its production prefix.

config/api.py wires the router into the real API at integration time; the
tests mount their own NinjaAPI (ninja allows one router on multiple API
instances) so they exercise the exact production paths without depending on
that wiring order.
"""

from django.urls import URLPattern, URLResolver, path
from ninja import NinjaAPI

from apps.accounts.api import router
from apps.core.envelope import register_exception_handlers

api = NinjaAPI(urls_namespace="accounts-tests")
register_exception_handlers(api)
api.add_router("/accounts/", router)

urlpatterns: list[URLPattern | URLResolver] = [
    path("api/", api.urls),
]
