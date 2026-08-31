"""Tests for the self-service password change endpoint.

POST /api/accounts/me/password/ is the one credential write a non-superuser
can reach; clearing password_needs_reset here is what releases a flagged
session from the auth-layer password gate.
"""

from typing import TYPE_CHECKING

import pytest
from django.test import Client

from apps.accounts.models import Staff

if TYPE_CHECKING:
    from django.test.client import _MonkeyPatchedWSGIResponse

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.urls("apps.accounts.tests.urls"),
]

LOGIN_PATH = "/api/accounts/token/"
CHANGE_PATH = "/api/accounts/me/password/"

PASSWORD = "s3cret-Pass!"
NEW_PASSWORD = "Fresh-Pass-9!"


@pytest.fixture
def staff() -> Staff:
    return Staff.objects.create_user(
        office_email="jo@example.com",
        password=PASSWORD,
        first_name="Jo",
        last_name="Bloggs",
    )


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


def login_status(username: str, password: str) -> int:
    return (
        Client()
        .post(
            LOGIN_PATH,
            data={"username": username, "password": password},
            content_type="application/json",
        )
        .status_code
    )


class TestPasswordChange:
    def test_change_sets_the_new_password_and_clears_the_flag(self, staff: Staff) -> None:
        staff.password_needs_reset = True
        staff.save(update_fields=["password_needs_reset", "updated_at"])
        client = logged_in_client(staff)

        response = change(client, PASSWORD, NEW_PASSWORD)

        assert response.status_code == 200
        staff.refresh_from_db()
        assert staff.check_password(NEW_PASSWORD)
        assert staff.password_needs_reset is False
        # The credential really rotated at the login boundary, not just in the hash.
        assert login_status("jo@example.com", PASSWORD) == 401
        assert login_status("jo@example.com", NEW_PASSWORD) == 200

    def test_wrong_current_password_is_a_400_and_changes_nothing(self, staff: Staff) -> None:
        staff.password_needs_reset = True
        staff.save(update_fields=["password_needs_reset", "updated_at"])
        client = logged_in_client(staff)

        response = change(client, "not-the-password", NEW_PASSWORD)

        assert response.status_code == 400
        assert "Current password is incorrect." in response.json()["detail"]
        staff.refresh_from_db()
        assert staff.check_password(PASSWORD)
        assert staff.password_needs_reset is True

    def test_weak_new_password_is_a_400_naming_the_rule(self, staff: Staff) -> None:
        client = logged_in_client(staff)

        response = change(client, PASSWORD, "password")

        assert response.status_code == 400
        assert "too common" in response.json()["detail"]
        staff.refresh_from_db()
        assert staff.check_password(PASSWORD)

    def test_anonymous_is_401(self) -> None:
        assert change(Client(), PASSWORD, NEW_PASSWORD).status_code == 401

    def test_reentering_the_current_password_is_refused(self, staff: Staff) -> None:
        """A forced change satisfied by the admin-issued temp password would
        keep the account on a credential someone else knows."""
        staff.password_needs_reset = True
        staff.save(update_fields=["password_needs_reset", "updated_at"])
        client = logged_in_client(staff)

        response = change(client, PASSWORD, PASSWORD)

        assert response.status_code == 400
        assert "must be different" in response.json()["detail"]
        staff.refresh_from_db()
        assert staff.password_needs_reset is True

    def test_a_change_evicts_every_other_session(self, staff: Staff) -> None:
        """Tokens carry a password fingerprint: the attacker who knew the old
        password and holds cookies is who the change exists to lock out."""
        changer = logged_in_client(staff)
        other_session = logged_in_client(staff)
        assert other_session.get("/api/accounts/me/").status_code == 200

        assert change(changer, PASSWORD, NEW_PASSWORD).status_code == 200

        assert other_session.get("/api/accounts/me/").status_code == 401
        # The stale refresh token must not mint its way back in either.
        assert (
            other_session.post(
                "/api/accounts/token/refresh/", data={}, content_type="application/json"
            ).status_code
            == 401
        )

    def test_the_changer_stays_signed_in(self, staff: Staff) -> None:
        """The change response re-mints the caller's own cookies — without
        that, changing your password would log you out mid-session."""
        client = logged_in_client(staff)

        assert change(client, PASSWORD, NEW_PASSWORD).status_code == 200

        assert client.get("/api/accounts/me/").status_code == 200
