from django.urls import path
from rest_framework_simplejwt.views import TokenVerifyView

from apps.accounts.views.password_views import SecurityPasswordChangeView
from apps.accounts.views.staff_api import (
    StaffListCreateAPIView,
    StaffRetrieveUpdateDestroyAPIView,
)
from apps.accounts.views.staff_views import (
    StaffListAPIView,
    get_staff_rates,
)
from apps.accounts.views.token_view import (
    CustomTokenObtainPairView,
    CustomTokenRefreshView,
)
from apps.accounts.views.user_profile_view import (
    GetCurrentUserAPIView,
    LogoutUserAPIView,
)

app_name = "accounts"

urlpatterns = [
    # Staff API
    path("staff/all/", StaffListAPIView.as_view(), name="api_staff_all_list"),
    path("staff/rates/<uuid:staff_id>/", get_staff_rates, name="get_staff_rates"),
    # JWT endpoints
    path("token/", CustomTokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("token/refresh/", CustomTokenRefreshView.as_view(), name="token_refresh"),
    path("token/verify/", TokenVerifyView.as_view(), name="token_verify"),
    # User profile API endpoints
    path("me/", GetCurrentUserAPIView.as_view(), name="get_current_user"),
    path("logout/", LogoutUserAPIView.as_view(), name="api_logout"),
    path(
        "password_change/", SecurityPasswordChangeView.as_view(), name="password_change"
    ),
    # Staff API RESTful endpoints
    path("staff/", StaffListCreateAPIView.as_view(), name="api_staff_list_create"),
    path(
        "staff/<uuid:pk>/",
        StaffRetrieveUpdateDestroyAPIView.as_view(),
        name="api_staff_detail",
    ),
]
