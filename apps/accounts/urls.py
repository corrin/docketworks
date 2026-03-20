from django.contrib.auth import views as auth_views
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
    path("api/staff/all/", StaffListAPIView.as_view(), name="api_staff_all_list"),
    path("api/staff/rates/<uuid:staff_id>/", get_staff_rates, name="get_staff_rates"),
    # JWT endpoints
    path("api/token/", CustomTokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("api/token/refresh/", CustomTokenRefreshView.as_view(), name="token_refresh"),
    path("api/token/verify/", TokenVerifyView.as_view(), name="token_verify"),
    # User profile API endpoints
    path("me/", GetCurrentUserAPIView.as_view(), name="get_current_user"),
    path("logout/", LogoutUserAPIView.as_view(), name="api_logout"),  # Authentication
    path(
        "login/",
        auth_views.LoginView.as_view(template_name="accounts/registration/login.html"),
        name="login",
    ),
    path("logout-session/", auth_views.LogoutView.as_view(), name="logout"),
    path(
        "password_change/", SecurityPasswordChangeView.as_view(), name="password_change"
    ),
    path(
        "password_change/done/",
        auth_views.PasswordChangeDoneView.as_view(
            template_name="accounts/registration/password_change_done.html"
        ),
        name="password_change_done",
    ),
    path(
        "password_reset/",
        auth_views.PasswordResetView.as_view(
            template_name="accounts/registration/password_reset_form.html",
            email_template_name="accounts/registration/password_reset_email.html",
            subject_template_name="accounts/registration/password_reset_subject.txt",
        ),
        name="password_reset",
    ),
    path(
        "password_reset/done/",
        auth_views.PasswordResetDoneView.as_view(
            template_name="accounts/registration/password_reset_done.html"
        ),
        name="password_reset_done",
    ),
    path(
        "reset/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            template_name="accounts/registration/password_reset_confirm.html"
        ),
        name="password_reset_confirm",
    ),
    path(
        "reset/done/",
        auth_views.PasswordResetCompleteView.as_view(
            template_name="accounts/registration/password_reset_complete.html"
        ),
        name="password_reset_complete",
    ),
    # Staff API RESTful endpoints
    path("api/staff/", StaffListCreateAPIView.as_view(), name="api_staff_list_create"),
    path(
        "api/staff/<uuid:pk>/",
        StaffRetrieveUpdateDestroyAPIView.as_view(),
        name="api_staff_detail",
    ),
]
