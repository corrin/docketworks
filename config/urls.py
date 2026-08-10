"""Root URL routing for the single Ninja API under ``/api/``."""

from django.conf import settings
from django.conf.urls.static import static
from django.urls import path

from apps.xero.oauth_views import xero_authenticate, xero_oauth_callback
from apps.xero.sync_stream import stream_xero_sync
from apps.xero.webhooks import XeroWebhookView
from config.api import api

urlpatterns = [
    # Browser-redirect OAuth endpoints, outside ninja and the OpenAPI schema.
    # The callback path is exact-parity: Xero's portal and XeroApp.redirect_uri
    # rows hold it verbatim.
    path("api/xero/authenticate/", xero_authenticate, name="api_xero_authenticate"),
    path("api/xero/oauth/callback/", xero_oauth_callback, name="xero_oauth_callback"),
    # Webhook receiver: exact-parity URL held by Xero's portal; HMAC-authenticated,
    # allowlisted through the auth-gate middleware.
    path("api/xero/webhook/", XeroWebhookView.as_view(), name="xero_webhook"),
    # SSE sync progress: infinite stream for EventSource, deliberately outside
    # the OpenAPI schema and generated client.
    path("api/xero/sync-stream/", stream_xero_sync, name="stream_xero_sync"),
    path("api/", api.urls),
]

if settings.DEBUG:
    # Staff icons etc: KanbanStaffOut/KanbanJobPersonOut return /media/ URLs
    # relative to the site root, which only resolve if something serves them.
    # Production serves MEDIA_ROOT from the proxy in front of Django; this is
    # the dev/E2E equivalent, standard Django and off outside DEBUG.
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
