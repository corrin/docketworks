"""Tests for the HttpOnly-cookie JWT authentication flow.

Cookie names, flags, and endpoint paths are hardcoded so a settings change
cannot silently move the browser authentication contract.
"""

from datetime import timedelta

import pytest
from django.test import Client
from django.utils import timezone

from apps.accounts.models import Staff
from apps.core.auth import jwt_cookie_config
from apps.core.models import AppError

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.urls("apps.accounts.tests.urls"),
]

LOGIN_PATH = "/api/accounts/token/"
REFRESH_PATH = "/api/accounts/token/refresh/"
LOGOUT_PATH = "/api/accounts/logout/"
ME_PATH = "/api/accounts/me/"

ACCESS_COOKIE = "access_token"
REFRESH_COOKIE = "refresh_token"

PASSWORD = "s3cret-Pass!"

ACCESS_MAX_AGE = 30 * 24 * 60 * 60  # 30 days
REFRESH_MAX_AGE = 90 * 24 * 60 * 60  # 90 days

AUTHENTICATION_REQUIRED = {
    "detail": "Authentication required.",
    "code": "authentication_required",
    "error_id": None,
}
INVALID_CREDENTIALS = {
    "detail": "Invalid e-mail or password.",
    "code": "invalid_credentials",
    "error_id": None,
}


@pytest.fixture
def staff() -> Staff:
    return Staff.objects.create_user(
        email="jo@example.com",
        password=PASSWORD,
        first_name="Jo",
        last_name="Bloggs",
        is_office_staff=True,
    )


def login(client: Client, staff: Staff) -> None:
    response = client.post(
        LOGIN_PATH,
        data={"username": staff.email, "password": PASSWORD},
        content_type="application/json",
    )
    assert response.status_code == 200


class TestLogin:
    def test_login_sets_httponly_cookies_and_returns_empty_body(self, staff: Staff) -> None:
        client = Client()
        response = client.post(
            LOGIN_PATH,
            data={"username": staff.email, "password": PASSWORD},
            content_type="application/json",
        )

        assert response.status_code == 200
        # Cookie mode never exposes tokens in the response body.
        assert response.json() == {"password_needs_reset": False}

        access = response.cookies[ACCESS_COOKIE]
        assert access.value
        assert access["httponly"]
        assert access["samesite"] == "Lax"
        assert int(access["max-age"]) == ACCESS_MAX_AGE
        assert bool(access["secure"]) is jwt_cookie_config().access_secure

        refresh = response.cookies[REFRESH_COOKIE]
        assert refresh.value
        assert refresh["httponly"]
        assert refresh["samesite"] == "Lax"
        assert int(refresh["max-age"]) == REFRESH_MAX_AGE
        assert bool(refresh["secure"]) is jwt_cookie_config().refresh_secure

    def test_login_reports_password_needs_reset(self, staff: Staff) -> None:
        staff.password_needs_reset = True
        staff.save()

        response = Client().post(
            LOGIN_PATH,
            data={"username": staff.email, "password": PASSWORD},
            content_type="application/json",
        )

        assert response.status_code == 200
        assert response.json() == {"password_needs_reset": True}
        assert response.cookies[ACCESS_COOKIE].value

    def test_wrong_password_is_401_with_no_cookies(self, staff: Staff) -> None:
        response = Client().post(
            LOGIN_PATH,
            data={"username": staff.email, "password": "wrong-password"},
            content_type="application/json",
        )

        assert response.status_code == 401
        assert response.json() == INVALID_CREDENTIALS
        assert ACCESS_COOKIE not in response.cookies
        assert REFRESH_COOKIE not in response.cookies
        assert not AppError.objects.exists()

    @pytest.mark.usefixtures("staff")
    def test_departed_staff_rejected_at_login(self, staff: Staff) -> None:
        """Login itself must 401 for departed staff (not just later requests).

        Regression: minting valid cookies for a departed user traps them in a
        silent login/redirect loop (200 at login, 401 everywhere else).
        """
        staff.date_left = timezone.localdate() - timedelta(days=1)
        staff.save()

        response = Client().post(
            LOGIN_PATH,
            data={"username": staff.email, "password": PASSWORD},
            content_type="application/json",
        )

        assert response.status_code == 401
        assert response.json() == INVALID_CREDENTIALS
        assert ACCESS_COOKIE not in response.cookies
        assert REFRESH_COOKIE not in response.cookies

    def test_unknown_user_is_401_with_no_cookies(self) -> None:
        response = Client().post(
            LOGIN_PATH,
            data={"username": "nobody@example.com", "password": PASSWORD},
            content_type="application/json",
        )

        assert response.status_code == 401
        assert response.json() == INVALID_CREDENTIALS
        assert ACCESS_COOKIE not in response.cookies
        assert not AppError.objects.exists()


class TestMe:
    def test_me_requires_auth(self) -> None:
        response = Client().get(ME_PATH)
        assert response.status_code == 401
        assert response.json() == AUTHENTICATION_REQUIRED
        assert response.headers["WWW-Authenticate"] == "Cookie"
        assert not AppError.objects.exists()

    def test_me_rejects_garbage_token(self) -> None:
        client = Client()
        client.cookies[ACCESS_COOKIE] = "not-a-jwt"
        response = client.get(ME_PATH)
        assert response.status_code == 401
        assert response.json() == AUTHENTICATION_REQUIRED
        assert not AppError.objects.exists()

    def test_me_returns_v1_user_profile_shape(self, staff: Staff) -> None:
        client = Client()
        login(client, staff)

        response = client.get(ME_PATH)

        assert response.status_code == 200
        assert response.json() == {
            "id": str(staff.id),
            "username": staff.email,
            "email": staff.email,
            "first_name": "Jo",
            "last_name": "Bloggs",
            "preferred_name": None,
            "fullName": "Jo Bloggs",
            "is_office_staff": True,
            "is_superuser": False,
        }

    def test_me_rejected_for_departed_staff(self, staff: Staff) -> None:
        client = Client()
        login(client, staff)

        staff.date_left = timezone.localdate() - timedelta(days=1)
        staff.save()

        response = client.get(ME_PATH)
        assert response.status_code == 401
        assert response.json() == AUTHENTICATION_REQUIRED


class TestTokenRefresh:
    def test_refresh_rotates_access_cookie_from_refresh_cookie(self, staff: Staff) -> None:
        client = Client()
        login(client, staff)
        old_access = client.cookies[ACCESS_COOKIE].value

        response = client.post(REFRESH_PATH, data={}, content_type="application/json")

        assert response.status_code == 200
        assert response.json() == {}
        new_access = response.cookies[ACCESS_COOKIE]
        assert new_access.value
        assert new_access.value != old_access
        assert new_access["httponly"]
        assert int(new_access["max-age"]) == ACCESS_MAX_AGE
        # Refresh-token rotation is disabled, so no new refresh cookie is set.
        assert REFRESH_COOKIE not in response.cookies

    def test_refresh_accepts_token_in_body(self, staff: Staff) -> None:
        client = Client()
        login(client, staff)
        refresh_value = client.cookies[REFRESH_COOKIE].value

        fresh_client = Client()
        response = fresh_client.post(
            REFRESH_PATH,
            data={"refresh": refresh_value},
            content_type="application/json",
        )

        assert response.status_code == 200
        assert response.cookies[ACCESS_COOKIE].value

    def test_refresh_without_token_is_401(self) -> None:
        response = Client().post(REFRESH_PATH, data={}, content_type="application/json")
        assert response.status_code == 401
        assert response.json() == AUTHENTICATION_REQUIRED
        assert response.cookies[ACCESS_COOKIE].value == ""
        assert response.cookies[REFRESH_COOKIE].value == ""
        assert not AppError.objects.exists()

    def test_refresh_with_invalid_token_is_401(self) -> None:
        response = Client().post(
            REFRESH_PATH,
            data={"refresh": "not-a-jwt"},
            content_type="application/json",
        )
        assert response.status_code == 401
        assert response.json() == AUTHENTICATION_REQUIRED
        assert response.cookies[ACCESS_COOKIE].value == ""
        assert response.cookies[REFRESH_COOKIE].value == ""
        assert not AppError.objects.exists()

    def test_refresh_rejects_and_clears_departed_staff(self, staff: Staff) -> None:
        client = Client()
        login(client, staff)
        staff.date_left = timezone.localdate() - timedelta(days=1)
        staff.save()

        response = client.post(REFRESH_PATH, data={}, content_type="application/json")

        assert response.status_code == 401
        assert response.json() == AUTHENTICATION_REQUIRED
        assert response.cookies[ACCESS_COOKIE].value == ""
        assert response.cookies[REFRESH_COOKIE].value == ""

    def test_refresh_rejects_and_clears_deleted_staff(self, staff: Staff) -> None:
        client = Client()
        login(client, staff)
        staff.delete()

        response = client.post(REFRESH_PATH, data={}, content_type="application/json")

        assert response.status_code == 401
        assert response.json() == AUTHENTICATION_REQUIRED
        assert response.cookies[ACCESS_COOKIE].value == ""
        assert response.cookies[REFRESH_COOKIE].value == ""


class TestLogout:
    def test_logout_clears_cookies(self, staff: Staff) -> None:
        client = Client()
        login(client, staff)

        response = client.post(LOGOUT_PATH)

        assert response.status_code == 200
        assert response.json() == {"success": True, "message": "Successfully logged out"}
        assert response.cookies[ACCESS_COOKIE].value == ""
        assert response.cookies[REFRESH_COOKIE].value == ""
        assert int(response.cookies[ACCESS_COOKIE]["max-age"]) == 0
        assert int(response.cookies[REFRESH_COOKIE]["max-age"]) == 0

    def test_logout_needs_no_auth(self) -> None:
        response = Client().post(LOGOUT_PATH)
        assert response.status_code == 200
