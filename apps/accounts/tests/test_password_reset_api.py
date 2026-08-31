"""Tests for the forgot-password flow.

POST /api/accounts/password-reset/ answers a fixed 200 whether or not the
email has an account — the anonymous contract must not reveal which addresses
exist. The emailed link carries uid+token for
POST /api/accounts/password-reset/confirm/, whose refusals are DECLARED 400
bodies (the envelope masks anonymous exception text, and the validator's
reason is exactly what this caller must read).
"""

import re
from datetime import date
from typing import TYPE_CHECKING

import pytest
from django.test import Client

import apps.accounts.tasks as accounts_tasks
from apps.accounts.models import Staff

if TYPE_CHECKING:
    from django.test.client import _MonkeyPatchedWSGIResponse

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.urls("apps.accounts.tests.urls"),
]

LOGIN_PATH = "/api/accounts/token/"
REQUEST_PATH = "/api/accounts/password-reset/"
CONFIRM_PATH = "/api/accounts/password-reset/confirm/"

PASSWORD = "s3cret-Pass!"
NEW_PASSWORD = "Fresh-Pass-9!"
INVALID_LINK_DETAIL = "This reset link is invalid or has expired."

LINK_PATTERN = re.compile(r"/reset-password\?uid=(?P<uid>[^&\s]+)&token=(?P<token>[^&\s]+)")


class SentEmail:
    def __init__(self, to: str, subject: str, body: str) -> None:
        self.to = to
        self.subject = subject
        self.body = body


@pytest.fixture
def outbox(monkeypatch: pytest.MonkeyPatch) -> list[SentEmail]:
    sent: list[SentEmail] = []

    def capture(to: str, subject: str, body: str) -> str:
        sent.append(SentEmail(to, subject, body))
        return "fake-gmail-id"

    # Patched at the task's own import (CELERY_TASK_ALWAYS_EAGER runs the
    # queued send inline in tests), so the enqueue path is exercised too.
    monkeypatch.setattr(accounts_tasks, "send_company_email", capture)
    return sent


@pytest.fixture
def staff() -> Staff:
    return Staff.objects.create_user(
        office_email="jo@example.com",
        password=PASSWORD,
        first_name="Jo",
        last_name="Bloggs",
    )


def request_reset(email: str) -> "_MonkeyPatchedWSGIResponse":
    return Client().post(REQUEST_PATH, data={"email": email}, content_type="application/json")


def confirm(uid: str, token: str, new_password: str) -> "_MonkeyPatchedWSGIResponse":
    return Client().post(
        CONFIRM_PATH,
        data={"uid": uid, "token": token, "new_password": new_password},
        content_type="application/json",
    )


def request_reset_ok(email: str, outbox: list[SentEmail]) -> tuple[str, str]:
    """Request a reset and return the link parts, failing loudly on a 500."""
    response = request_reset(email)
    assert response.status_code == 200, response.json()
    return link_parts(outbox)


def link_parts(outbox: list[SentEmail]) -> tuple[str, str]:
    assert len(outbox) == 1
    match = LINK_PATTERN.search(outbox[0].body)
    assert match is not None, f"no reset link in email body: {outbox[0].body!r}"
    return match.group("uid"), match.group("token")


def login_response(username: str, password: str) -> "_MonkeyPatchedWSGIResponse":
    return Client().post(
        LOGIN_PATH,
        data={"username": username, "password": password},
        content_type="application/json",
    )


class TestPasswordResetRequest:
    def test_known_email_gets_a_link_that_resets_the_password(
        self, staff: Staff, outbox: list[SentEmail]
    ) -> None:
        staff.password_needs_reset = True
        staff.save(update_fields=["password_needs_reset", "updated_at"])

        response = request_reset("jo@example.com")

        assert response.status_code == 200
        uid, token = link_parts(outbox)
        assert outbox[0].to == "jo@example.com"

        confirm_response = confirm(uid, token, NEW_PASSWORD)

        assert confirm_response.status_code == 200
        assert login_response("jo@example.com", PASSWORD).status_code == 401
        fresh_login = login_response("jo@example.com", NEW_PASSWORD)
        assert fresh_login.status_code == 200
        assert fresh_login.json()["password_needs_reset"] is False

    def test_unknown_email_is_the_same_200_and_sends_nothing(self, outbox: list[SentEmail]) -> None:
        response = request_reset("nobody@example.com")

        assert response.status_code == 200
        assert outbox == []

    def test_departed_staff_get_no_email(self, staff: Staff, outbox: list[SentEmail]) -> None:
        staff.date_left = date(2020, 1, 1)
        staff.save()

        response = request_reset("jo@example.com")

        assert response.status_code == 200
        assert outbox == []

    @pytest.mark.usefixtures("staff")
    def test_email_match_is_case_insensitive(self, outbox: list[SentEmail]) -> None:
        response = request_reset("JO@example.com")

        assert response.status_code == 200
        assert len(outbox) == 1

    def test_a_payroll_only_address_gets_its_reset(self, outbox: list[SentEmail]) -> None:
        """Login accepts either email field, so reset must too — wage staff
        often hold only a payroll mailbox."""
        Staff.objects.create_user(
            office_email=None,
            payroll_email="wages@example.com",
            password=PASSWORD,
            first_name="Pay",
            last_name="Roll",
        )

        response = request_reset("wages@example.com")

        assert response.status_code == 200
        assert len(outbox) == 1
        assert outbox[0].to == "wages@example.com"


class TestPasswordResetConfirm:
    def test_a_wrong_token_is_refused_and_changes_nothing(
        self, staff: Staff, outbox: list[SentEmail]
    ) -> None:
        uid, _token = request_reset_ok("jo@example.com", outbox)
        before = staff.password

        response = confirm(uid, "garbage-token", NEW_PASSWORD)

        assert response.status_code == 400
        assert response.json()["detail"] == INVALID_LINK_DETAIL
        staff.refresh_from_db()
        assert staff.password == before

    def test_a_garbled_uid_is_the_same_refusal(self) -> None:
        response = confirm("not-base64!", "whatever", NEW_PASSWORD)

        assert response.status_code == 400
        assert response.json()["detail"] == INVALID_LINK_DETAIL

    @pytest.mark.usefixtures("staff")
    def test_a_weak_new_password_is_refused_with_the_validator_reason(
        self, outbox: list[SentEmail]
    ) -> None:
        uid, token = request_reset_ok("jo@example.com", outbox)

        response = confirm(uid, token, "password")

        assert response.status_code == 400
        assert "too common" in response.json()["detail"]

    @pytest.mark.usefixtures("staff")
    def test_a_used_link_does_not_work_twice(self, outbox: list[SentEmail]) -> None:
        """The token hashes the password, so a successful reset burns it."""
        uid, token = request_reset_ok("jo@example.com", outbox)
        assert confirm(uid, token, NEW_PASSWORD).status_code == 200

        response = confirm(uid, token, "Another-Pass-7!")

        assert response.status_code == 400
        assert response.json()["detail"] == INVALID_LINK_DETAIL
