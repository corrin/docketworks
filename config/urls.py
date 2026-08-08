"""Root URL routing for the single Ninja API under ``/api/``."""

from django.urls import path

from apps.xero.oauth_views import xero_authenticate, xero_oauth_callback
from config.api import api

urlpatterns = [
    # Browser-redirect OAuth endpoints, outside ninja and the OpenAPI schema.
    # The callback path is exact-parity: Xero's portal and XeroApp.redirect_uri
    # rows hold it verbatim.
    path("api/xero/authenticate/", xero_authenticate, name="api_xero_authenticate"),
    path("api/xero/oauth/callback/", xero_oauth_callback, name="xero_oauth_callback"),
    path("api/", api.urls),
]
