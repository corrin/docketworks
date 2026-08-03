"""Test URLconf mounting the purchasing router at its production prefixes.

config/api.py wires the router into the real API at integration time; the tests
mount their own NinjaAPI (ninja allows one router on multiple API instances) so
they exercise the exact production paths without depending on that wiring order
(house pattern: apps/job/tests/urls.py).

The job router is mounted here too: the cost-line approve endpoint closes the
seam this slice was blocked on, and its tests live beside the purchasing ones.
"""

from django.urls import URLPattern, URLResolver, path
from ninja import NinjaAPI

from apps.core.envelope import register_exception_handlers
from apps.job.api import router as job_router
from apps.purchasing.api import router as purchasing_router

api = NinjaAPI(urls_namespace="purchasing-tests")
register_exception_handlers(api)
api.add_router("/", purchasing_router)
api.add_router("/", job_router)

urlpatterns: list[URLPattern | URLResolver] = [
    path("api/", api.urls),
]
