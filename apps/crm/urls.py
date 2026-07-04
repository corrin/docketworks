from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.crm.views.phone_call_views import (
    PhoneCallRecordingViewSet,
    PhoneCallRecordViewSet,
    PhoneEndpointViewSet,
    PhoneProviderSettingsView,
)

app_name = "crm"

router = DefaultRouter()
router.register("phone-endpoints", PhoneEndpointViewSet, basename="phone-endpoint")
router.register("phone-calls", PhoneCallRecordViewSet, basename="phone-call")
router.register(
    "phone-call-recordings",
    PhoneCallRecordingViewSet,
    basename="phone-call-recording",
)

urlpatterns = [
    path(
        "phone-provider-settings/",
        PhoneProviderSettingsView.as_view(),
        name="phone-provider-settings",
    ),
    path("", include(router.urls)),
]
