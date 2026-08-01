from unittest.mock import patch

import pytest
from django.test import RequestFactory, override_settings
from rest_framework.test import APIClient

from apps.accounts.models import Staff
from apps.accounts.views import user_profile_view
from apps.accounts.views.user_profile_view import LogoutUserAPIView
from apps.workflow import authentication, exception_handlers
from apps.workflow.authentication import JWTAuthentication
from apps.workflow.models import AppError

TEST_CLIENT_IP = "192.0.2.10"
TEST_WEBHOOK_IP = "192.0.2.20"
TEST_PROXY_IP = "10.0.0.1"


@override_settings(ENABLE_JWT_AUTH=True)
def test_jwt_auth_logs_cookie_miss_with_request_context() -> None:
    request = RequestFactory().get(
        "/api/accounts/me/",
        HTTP_X_FORWARDED_FOR=f"{TEST_CLIENT_IP}, {TEST_PROXY_IP}",
    )

    with patch.object(authentication.logger, "info") as log_info:
        assert JWTAuthentication().authenticate(request) is None

    log_info.assert_called_once()
    _, *log_args = log_info.call_args.args
    assert log_args == [
        "GET",
        "/api/accounts/me/",
        TEST_CLIENT_IP,
        "access_token",
        False,
        False,
    ]


@override_settings(ENABLE_JWT_AUTH=True)
def test_jwt_auth_does_not_log_cookie_miss_for_xero_webhook() -> None:
    request = RequestFactory().post(
        "/api/xero/webhook/",
        HTTP_X_FORWARDED_FOR=f"{TEST_WEBHOOK_IP}, {TEST_PROXY_IP}",
    )

    with patch.object(authentication.logger, "info") as log_info:
        assert JWTAuthentication().authenticate(request) is None

    log_info.assert_not_called()


@pytest.mark.django_db
@override_settings(ENABLE_JWT_AUTH=True)
def test_current_user_anonymous_session_probe_is_not_an_auth_warning() -> None:
    client = APIClient()

    with patch.object(exception_handlers.auth_logger, "warning") as log_warning:
        response = client.get("/api/accounts/me/")

    assert response.status_code == 401
    assert response.json() == {
        "detail": "Authentication credentials were not provided."
    }
    log_warning.assert_not_called()
    assert AppError.objects.count() == 0


@pytest.mark.django_db
@override_settings(ENABLE_JWT_AUTH=True)
def test_current_user_returns_authenticated_profile() -> None:
    user = Staff.objects.create_user(
        email="profile@example.test",
        password="testpass",
        first_name="Profile",
        last_name="User",
    )
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.get("/api/accounts/me/")

    assert response.status_code == 200
    assert response.json()["email"] == user.email


@pytest.mark.django_db
@override_settings(ENABLE_JWT_AUTH=True, DEBUG=False)
def test_current_user_invalid_cookie_remains_an_auth_warning() -> None:
    client = APIClient()
    client.cookies["access_token"] = "not-a-valid-jwt"

    with patch.object(exception_handlers.auth_logger, "warning") as log_warning:
        response = client.get("/api/accounts/me/")

    assert response.status_code == 401
    log_warning.assert_called_once()
    assert AppError.objects.count() == 1


@pytest.mark.django_db
def test_logout_logs_cookie_presence_without_token_values() -> None:
    request = RequestFactory().post(
        "/api/accounts/logout/",
        HTTP_X_FORWARDED_FOR=f"{TEST_CLIENT_IP}, {TEST_PROXY_IP}",
    )
    request.COOKIES["access_token"] = "secret-access-token"
    request.COOKIES["refresh_token"] = "secret-refresh-token"

    with patch.object(user_profile_view.auth_logger, "info") as log_info:
        response = LogoutUserAPIView.as_view()(request)

    assert response.status_code == 200
    log_info.assert_called_once()
    _, *log_args = log_info.call_args.args
    assert log_args == [TEST_CLIENT_IP, True, True]


@pytest.mark.django_db
def test_logout_clears_cookies_even_when_access_cookie_is_invalid() -> None:
    client = APIClient()
    client.cookies["access_token"] = "not-a-valid-jwt"
    client.cookies["refresh_token"] = "refresh-token-value"

    response = client.post("/api/accounts/logout/")

    assert response.status_code == 200
    assert response.cookies["access_token"].value == ""
    assert response.cookies["access_token"]["max-age"] == 0
    assert response.cookies["refresh_token"].value == ""
    assert response.cookies["refresh_token"]["max-age"] == 0
