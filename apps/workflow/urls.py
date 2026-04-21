"""
URL Configuration for Workflow App

All paths are relative — mounted at /api/ by the top-level urls.py.
"""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.workflow.api.enums import get_enum_choices
from apps.workflow.views.ai_provider_viewset import AIProviderViewSet
from apps.workflow.views.app_error_grouped_view import (
    AppErrorGroupedListView,
    AppErrorGroupedMarkResolvedView,
    AppErrorGroupedMarkUnresolvedView,
    XeroErrorGroupedListView,
    XeroErrorGroupedMarkResolvedView,
    XeroErrorGroupedMarkUnresolvedView,
)
from apps.workflow.views.app_error_view import (
    AppErrorDetailAPIView,
    AppErrorListAPIView,
    AppErrorRestListView,
    AppErrorViewSet,
)
from apps.workflow.views.build_id_view import BuildIdAPIView
from apps.workflow.views.company_defaults_api import CompanyDefaultsAPIView
from apps.workflow.views.company_defaults_logo_api import CompanyDefaultsLogoAPIView
from apps.workflow.views.company_defaults_schema_api import CompanyDefaultsSchemaAPIView
from apps.workflow.views.xero import xero_view
from apps.workflow.views.xero_pay_item_viewset import XeroPayItemViewSet
from apps.workflow.xero_webhooks import XeroWebhookView

# ---------------------------------------------------------------------------
# DRF Router setup for AI Provider and AppError endpoints
# ---------------------------------------------------------------------------
router = DefaultRouter()
router.register("ai-providers", AIProviderViewSet, basename="ai-provider")
router.register("app-errors", AppErrorViewSet, basename="app-error")
router.register("xero-pay-items", XeroPayItemViewSet, basename="xero-pay-item")

urlpatterns = [
    path("build-id/", BuildIdAPIView.as_view(), name="build_id"),
    path("enums/<str:enum_name>/", get_enum_choices, name="get_enum_choices"),
    path(
        "xero/authenticate/",
        xero_view.xero_authenticate,
        name="api_xero_authenticate",
    ),
    path(
        "xero/oauth/callback/",
        xero_view.xero_oauth_callback,
        name="xero_oauth_callback",
    ),
    path(
        "xero/disconnect/",
        xero_view.xero_disconnect,
        name="xero_disconnect",
    ),
    path(
        "xero/sync-stream/",
        xero_view.stream_xero_sync,
        name="stream_xero_sync",
    ),
    path(
        "xero/create_invoice/<uuid:job_id>",
        xero_view.create_xero_invoice,
        name="create_invoice",
    ),
    path(
        "xero/delete_invoice/<uuid:job_id>",
        xero_view.delete_xero_invoice,
        name="delete_invoice",
    ),
    path(
        "xero/create_quote/<uuid:job_id>",
        xero_view.create_xero_quote,
        name="create_quote",
    ),
    path(
        "xero/delete_quote/<uuid:job_id>",
        xero_view.delete_xero_quote,
        name="delete_quote",
    ),
    path(
        "xero/sync-info/",
        xero_view.get_xero_sync_info,
        name="xero_sync_info",
    ),
    path(
        "xero/create_purchase_order/<uuid:purchase_order_id>",
        xero_view.create_xero_purchase_order,
        name="create_xero_purchase_order",
    ),
    path(
        "xero/delete_purchase_order/<uuid:purchase_order_id>",
        xero_view.delete_xero_purchase_order,
        name="delete_xero_purchase_order",
    ),
    path(
        "xero/sync/",
        xero_view.start_xero_sync,
        name="synchronise_xero_data",
    ),
    path(
        "xero/webhook/",
        XeroWebhookView.as_view(),
        name="xero_webhook",
    ),
    path(
        "xero/ping/",
        xero_view.xero_ping,
        name="xero_ping",
    ),
    path(
        "app-errors/grouped/",
        AppErrorGroupedListView.as_view(),
        name="app-error-grouped-list",
    ),
    path(
        "app-errors/grouped/mark_resolved/",
        AppErrorGroupedMarkResolvedView.as_view(),
        name="app-error-grouped-mark-resolved",
    ),
    path(
        "app-errors/grouped/mark_unresolved/",
        AppErrorGroupedMarkUnresolvedView.as_view(),
        name="app-error-grouped-mark-unresolved",
    ),
    path(
        "app-errors/",
        AppErrorListAPIView.as_view(),
        name="app-error-list",
    ),
    path(
        "app-errors/<uuid:pk>/",
        AppErrorDetailAPIView.as_view(),
        name="app-error-detail",
    ),
    path(
        "rest/app-errors/",
        AppErrorRestListView.as_view(),
        name="app-error-rest-list",
    ),
    path(
        "xero-errors/grouped/",
        XeroErrorGroupedListView.as_view(),
        name="xero-error-grouped-list",
    ),
    path(
        "xero-errors/grouped/mark_resolved/",
        XeroErrorGroupedMarkResolvedView.as_view(),
        name="xero-error-grouped-mark-resolved",
    ),
    path(
        "xero-errors/grouped/mark_unresolved/",
        XeroErrorGroupedMarkUnresolvedView.as_view(),
        name="xero-error-grouped-mark-unresolved",
    ),
    path(
        "xero-errors/",
        xero_view.XeroErrorListAPIView.as_view(),
        name="xero-error-list",
    ),
    path(
        "xero-errors/<uuid:pk>/",
        xero_view.XeroErrorDetailAPIView.as_view(),
        name="xero-error-detail",
    ),
    path(
        "company-defaults/",
        CompanyDefaultsAPIView.as_view(),
        name="api_company_defaults",
    ),
    path(
        "company-defaults/upload-logo/",
        CompanyDefaultsLogoAPIView.as_view(),
        name="api_company_defaults_upload_logo",
    ),
    path(
        "company-defaults/schema/",
        CompanyDefaultsSchemaAPIView.as_view(),
        name="api_company_defaults_schema",
    ),
    # AI Provider CRUD & custom actions
    path("workflow/", include(router.urls)),
    # End of URL patterns
]
