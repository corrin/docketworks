"""Test URLconf mounting the crm router at its production prefix.

config/api.py wires the router into the real API at integration time; the
tests mount their own NinjaAPI (ninja allows one router on multiple API
instances) so they exercise the exact production paths — including the
production exception envelope — without depending on that wiring order.
"""

from django.urls import URLPattern, URLResolver, path
from ninja import NinjaAPI

from apps.core.envelope import register_exception_handlers
from apps.crm.api import router

api = NinjaAPI(urls_namespace="crm-tests")
register_exception_handlers(api)
api.add_router("/crm/", router)

urlpatterns: list[URLPattern | URLResolver] = [
    path("api/", api.urls),
]
