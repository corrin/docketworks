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
