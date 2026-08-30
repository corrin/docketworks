"""Root URL routing for the single Ninja API under ``/api/``."""

from django.conf import settings
from django.conf.urls.static import static
from django.urls import path

from apps.operations.events import data_versions_stream
from apps.timesheet.events import payroll_runs_stream
from apps.xero.events import xero_sync_stream
from apps.xero.oauth_views import xero_authenticate, xero_oauth_callback
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
    # Never-ending SSE response consumed by EventSource, so it mounts outside
    # ninja and the OpenAPI schema for the same reason the OAuth views do.
    # Beside its polling sibling at /api/data-versions/ rather than under an
    # /api/operations/ prefix nothing else uses: the two halves of one contract
    # have to be findable together. Django resolves in order, so this specific
    # path still wins over the ninja include below.
    path("api/data-versions/stream/", data_versions_stream, name="data_versions_stream"),
    # Opus: The posting itself runs in a Celery task; this endpoint only reports it.
    path(
        "api/timesheets/payroll/runs/stream/",
        payroll_runs_stream,
        name="payroll_runs_stream",
    ),
    # Fable: sync progress published by apps.xero.sync_worker; office-gated.
    # Beside its polling sibling /api/xero/sync-info/ for the same
    # findability reason as data-versions.
    path("api/xero/sync/stream/", xero_sync_stream, name="xero_sync_stream"),
    path("api/", api.urls),
]

if settings.DEBUG:
    # Staff icons etc: KanbanStaffOut/KanbanJobPersonOut return /media/ URLs
    # relative to the site root, which only resolve if something serves them.
    # Production serves MEDIA_ROOT from the proxy in front of Django; this is
    # the dev/E2E equivalent, standard Django and off outside DEBUG.
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
