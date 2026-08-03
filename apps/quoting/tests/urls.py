"""Test URLconf mounting the quoting router at its production prefixes.

config/api.py wires the router into the real API at integration time; the tests
mount their own NinjaAPI (ninja allows one router on multiple API instances) so
they exercise the exact production paths without depending on that wiring order
(house pattern: apps/job/tests/urls.py, apps/purchasing/tests/urls.py).
"""

from django.urls import URLPattern, URLResolver, path
from ninja import NinjaAPI

from apps.core.envelope import register_exception_handlers
from apps.quoting.api import router as quoting_router

api = NinjaAPI(urls_namespace="quoting-tests")
register_exception_handlers(api)
api.add_router("/", quoting_router)

urlpatterns: list[URLPattern | URLResolver] = [
    path("api/", api.urls),
]
