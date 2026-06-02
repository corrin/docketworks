from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.crm.views.phone_call_views import (
    PhoneCallRecordingViewSet,
    PhoneCallRecordViewSet,
    PhoneNumberClientMappingViewSet,
)

app_name = "crm"

router = DefaultRouter()
router.register("phone-calls", PhoneCallRecordViewSet, basename="phone-call")
router.register(
    "phone-number-mappings",
    PhoneNumberClientMappingViewSet,
    basename="phone-number-mapping",
)
router.register(
    "phone-call-recordings",
    PhoneCallRecordingViewSet,
    basename="phone-call-recording",
)

urlpatterns = [
    path("", include(router.urls)),
]
