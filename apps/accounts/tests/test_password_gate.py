"""Tests for the auth-layer password_needs_reset gate.

While the flag is set every authenticated request is refused with the typed
403 (code "password_change_required", error_id null, no AppError row) except
the allowlisted /me/ and /me/password/ paths — the session-resolution read and
the exit. The gate lives in CookieJWTAuth, so a frontend redirect is
navigation, never the control.
"""

from typing import TYPE_CHECKING

import pytest
from django.test import Client

from apps.accounts.models import Staff
from apps.core.models import AppError

if TYPE_CHECKING:
    from django.test.client import _MonkeyPatchedWSGIResponse

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.urls("apps.accounts.tests.urls"),
]

LOGIN_PATH = "/api/accounts/token/"
ME_PATH = "/api/accounts/me/"
CHANGE_PATH = "/api/accounts/me/password/"
GATED_PATH = "/api/accounts/staff/all/"
SUPERUSER_GATED_PATH = "/api/accounts/staff/"

PASSWORD = "s3cret-Pass!"
NEW_PASSWORD = "Fresh-Pass-9!"


@pytest.fixture
def flagged_staff() -> Staff:
    staff = Staff.objects.create_user(
        office_email="flagged@example.com",
        password=PASSWORD,
        first_name="Flag",
        last_name="Carrier",
    )
    staff.password_needs_reset = True
    staff.save(update_fields=["password_needs_reset", "updated_at"])
    return staff


def logged_in_client(staff: Staff) -> Client:
    client = Client()
    response = client.post(
        LOGIN_PATH,
        data={"username": staff.office_email, "password": PASSWORD},
        content_type="application/json",
    )
    assert response.status_code == 200
    return client


def change(client: Client, current: str, new: str) -> "_MonkeyPatchedWSGIResponse":
    return client.post(
        CHANGE_PATH,
        data={"current_password": current, "new_password": new},
        content_type="application/json",
    )


class TestPasswordGate:
    def test_flagged_session_is_refused_with_the_typed_403(self, flagged_staff: Staff) -> None:
        client = logged_in_client(flagged_staff)

        response = client.get(GATED_PATH)

        assert response.status_code == 403
        body = response.json()
        assert body["code"] == "password_change_required"
        assert body["error_id"] is None

    def test_the_typed_403_persists_no_app_error(self, flagged_staff: Staff) -> None:
        client = logged_in_client(flagged_staff)

        response = client.get(GATED_PATH)

        assert response.status_code == 403
        assert AppError.objects.count() == 0

    def test_me_stays_reachable_for_a_flagged_session(self, flagged_staff: Staff) -> None:
        client = logged_in_client(flagged_staff)

        response = client.get(ME_PATH)

        assert response.status_code == 200

    def test_changing_the_password_releases_the_gate(self, flagged_staff: Staff) -> None:
        client = logged_in_client(flagged_staff)
        assert client.get(GATED_PATH).status_code == 403

        response = change(client, PASSWORD, NEW_PASSWORD)

        assert response.status_code == 200
        assert client.get(GATED_PATH).status_code == 200

    def test_superuser_auth_refuses_the_same_way(self, flagged_staff: Staff) -> None:
        # The subclass inherits the gate from CookieJWTAuth.authenticate, so a
        # flagged superuser cannot reach superuser endpoints either.
        flagged_staff.is_superuser = True
        flagged_staff.save(update_fields=["is_superuser", "updated_at"])
        client = logged_in_client(flagged_staff)

        response = client.get(SUPERUSER_GATED_PATH)

        assert response.status_code == 403
        assert response.json()["code"] == "password_change_required"

    def test_an_unflagged_session_is_untouched(self, flagged_staff: Staff) -> None:
        flagged_staff.password_needs_reset = False
        flagged_staff.save(update_fields=["password_needs_reset", "updated_at"])
        client = logged_in_client(flagged_staff)

        assert client.get(GATED_PATH).status_code == 200
