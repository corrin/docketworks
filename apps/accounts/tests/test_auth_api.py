"""Tests for the ported v1 auth endpoints (HttpOnly-cookie JWT flow).

The cookie names, flags and endpoint paths asserted here are the v1 browser
contract: existing sessions must survive the v2 cutover, so the literals are
hardcoded deliberately rather than read from settings.
"""

from datetime import timedelta

import pytest
from django.test import Client
from django.utils import timezone

from apps.accounts.models import Staff
from apps.core.auth import jwt_cookie_config

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
        # Cookie mode: tokens never appear in the response body (v1 parity).
        assert response.json() == {}

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
        assert ACCESS_COOKIE not in response.cookies
        assert REFRESH_COOKIE not in response.cookies

    def test_unknown_user_is_401_with_no_cookies(self, staff: Staff) -> None:
        response = Client().post(
            LOGIN_PATH,
            data={"username": "nobody@example.com", "password": PASSWORD},
            content_type="application/json",
        )

        assert response.status_code == 401
        assert ACCESS_COOKIE not in response.cookies


class TestMe:
    def test_me_requires_auth(self) -> None:
        response = Client().get(ME_PATH)
        assert response.status_code == 401

    def test_me_rejects_garbage_token(self) -> None:
        client = Client()
        client.cookies[ACCESS_COOKIE] = "not-a-jwt"
        response = client.get(ME_PATH)
        assert response.status_code == 401

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
        # ROTATE_REFRESH_TOKENS=False (v1 parity): no new refresh cookie.
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

    def test_refresh_with_invalid_token_is_401(self) -> None:
        response = Client().post(
            REFRESH_PATH,
            data={"refresh": "not-a-jwt"},
            content_type="application/json",
        )
        assert response.status_code == 401


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
