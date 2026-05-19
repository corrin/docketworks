from unittest.mock import patch

import pytest
from django.test import RequestFactory, override_settings
from rest_framework.test import APIClient

from apps.accounts.views import user_profile_view
from apps.accounts.views.user_profile_view import LogoutUserAPIView
from apps.workflow import authentication
from apps.workflow.authentication import JWTAuthentication

TEST_CLIENT_IP = "192.0.2.10"
TEST_WEBHOOK_IP = "192.0.2.20"
TEST_PROXY_IP = "10.0.0.1"


@override_settings(ENABLE_JWT_AUTH=True)
def test_jwt_auth_logs_cookie_miss_with_request_context():
    request = RequestFactory().get(
        "/api/accounts/me/",
        HTTP_X_FORWARDED_FOR=f"{TEST_CLIENT_IP}, {TEST_PROXY_IP}",
    )

    with patch.object(authentication.logger, "info") as log_info:
        assert JWTAuthentication().authenticate(request) is None

    log_info.assert_called_once_with(
        "JWT AUTH MISS - method=%s path=%s ip=%s access_cookie=%s access_cookie_present=%s refresh_cookie_present=%s",
        "GET",
        "/api/accounts/me/",
        TEST_CLIENT_IP,
        "access_token",
        False,
        False,
    )


@override_settings(ENABLE_JWT_AUTH=True)
def test_jwt_auth_does_not_log_cookie_miss_for_xero_webhook():
    request = RequestFactory().post(
        "/api/xero/webhook/",
        HTTP_X_FORWARDED_FOR=f"{TEST_WEBHOOK_IP}, {TEST_PROXY_IP}",
    )

    with patch.object(authentication.logger, "info") as log_info:
        assert JWTAuthentication().authenticate(request) is None

    log_info.assert_not_called()


@pytest.mark.django_db
def test_logout_logs_cookie_presence_without_token_values():
    request = RequestFactory().post(
        "/api/accounts/logout/",
        HTTP_X_FORWARDED_FOR=f"{TEST_CLIENT_IP}, {TEST_PROXY_IP}",
    )
    request.COOKIES["access_token"] = "secret-access-token"
    request.COOKIES["refresh_token"] = "secret-refresh-token"

    with patch.object(user_profile_view.auth_logger, "info") as log_info:
        response = LogoutUserAPIView.as_view()(request)

    assert response.status_code == 200
    log_info.assert_called_once_with(
        "JWT LOGOUT REQUEST - ip=%s access_cookie_present=%s refresh_cookie_present=%s",
        TEST_CLIENT_IP,
        True,
        True,
    )


@pytest.mark.django_db
def test_logout_clears_cookies_even_when_access_cookie_is_invalid():
    client = APIClient()
    client.cookies["access_token"] = "not-a-valid-jwt"
    client.cookies["refresh_token"] = "refresh-token-value"

    response = client.post("/api/accounts/logout/")

    assert response.status_code == 200
    assert response.cookies["access_token"].value == ""
    assert response.cookies["access_token"]["max-age"] == 0
    assert response.cookies["refresh_token"].value == ""
    assert response.cookies["refresh_token"]["max-age"] == 0
