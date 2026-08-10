"""API tests for the kanban staff panel: GET /api/accounts/staff/all/.

Every authenticated user's view (no wage data), unlike the superuser-gated
admin list at GET /api/accounts/staff/ — see test_staff_list_api.py.
"""

from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from django.test import Client

from apps.accounts.models import Staff
from apps.company.tests.conftest import authenticate

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.urls("apps.accounts.tests.urls"),
]

URL = "/api/accounts/staff/all/"
PASSWORD = "s3cret-Pass!"


def make_staff(email: str, **extra: object) -> Staff:
    return Staff.objects.create_user(
        email=email,
        password=PASSWORD,
        first_name=str(extra.pop("first_name", "Test")),
        last_name=str(extra.pop("last_name", "Person")),
        **extra,
    )


def client_for(staff: Staff) -> Client:
    client = Client()
    authenticate(client, staff)
    return client


class TestAuth:
    def test_anonymous_is_rejected(self) -> None:
        assert Client().get(URL).status_code == 401

    def test_non_superuser_is_allowed(self) -> None:
        staff = make_staff("office@example.com", is_office_staff=True)
        assert client_for(staff).get(URL).status_code == 200


class TestDefaultListing:
    def test_excludes_departed_staff_by_default(self) -> None:
        requester = make_staff("requester@example.com")
        make_staff(
            "departed@example.com",
            first_name="Dee",
            date_left=date(2020, 1, 1),
        )

        body = client_for(requester).get(URL).json()

        display_names = {row["display_name"] for row in body}
        assert "Dee Person" not in display_names

    def test_default_includes_currently_active_staff(self) -> None:
        requester = make_staff("requester2@example.com")
        current = make_staff("current2@example.com", first_name="Cara")

        body = client_for(requester).get(URL).json()

        by_id = {row["id"] for row in body}
        assert str(current.id) in by_id


class TestDateFilter:
    def test_date_picks_staff_active_on_that_date(self) -> None:
        # date_joined must predate the query date too — the manager method
        # requires employment to have started by the target date, and the
        # default date_joined is "now" (real test-run time).
        joined = datetime(2023, 1, 1, tzinfo=UTC)
        requester = make_staff("requester3@example.com", date_joined=joined)
        gone_before = make_staff(
            "gone-before@example.com",
            first_name="Before",
            date_joined=joined,
            date_left=date(2024, 1, 1),
        )
        active_on_date = make_staff(
            "active-on-date@example.com",
            first_name="Active",
            date_joined=joined,
            date_left=date(2024, 6, 1),
        )

        response = client_for(requester).get(URL, {"date": "2024-03-01"})

        assert response.status_code == 200
        ids = {row["id"] for row in response.json()}
        assert str(active_on_date.id) in ids
        assert str(gone_before.id) not in ids


class TestIncludeInactive:
    def test_include_inactive_returns_departed_staff(self) -> None:
        requester = make_staff("requester4@example.com")
        departed = make_staff(
            "departed4@example.com",
            first_name="Departed",
            date_left=date(2020, 1, 1),
        )

        response = client_for(requester).get(URL, {"include_inactive": "true"})

        ids = {row["id"] for row in response.json()}
        assert str(departed.id) in ids

    def test_include_inactive_is_ignored_when_date_given(self) -> None:
        """v1 semantics: date wins over include_inactive."""
        joined = datetime(2023, 1, 1, tzinfo=UTC)
        requester = make_staff("requester5@example.com", date_joined=joined)
        gone_before = make_staff(
            "gone-before5@example.com",
            first_name="GoneBefore",
            date_joined=joined,
            date_left=date(2024, 1, 1),
        )

        response = client_for(requester).get(
            URL, {"date": "2024-06-01", "include_inactive": "true"}
        )

        ids = {row["id"] for row in response.json()}
        assert str(gone_before.id) not in ids


class TestActualUsers:
    def test_actual_users_excludes_payroll_excluded_ids(self) -> None:
        requester = make_staff("requester6@example.com")
        no_payroll = make_staff("no-payroll@example.com", first_name="NoPayroll")
        with_payroll = make_staff(
            "with-payroll@example.com",
            first_name="WithPayroll",
            xero_user_id=str(uuid4()),
        )

        response = client_for(requester).get(URL, {"actual_users": "true"})

        ids = {row["id"] for row in response.json()}
        assert str(with_payroll.id) in ids
        assert str(no_payroll.id) not in ids

    def test_actual_users_false_keeps_payroll_excluded_ids(self) -> None:
        requester = make_staff("requester7@example.com")
        no_payroll = make_staff("no-payroll7@example.com", first_name="NoPayroll7")

        response = client_for(requester).get(URL)

        ids = {row["id"] for row in response.json()}
        assert str(no_payroll.id) in ids


class TestResponseShape:
    def test_response_has_exactly_the_seven_fields(self) -> None:
        requester = make_staff("requester8@example.com", first_name="Req", last_name="Ester")

        body = client_for(requester).get(URL).json()

        row = next(item for item in body if item["id"] == str(requester.id))
        assert set(row.keys()) == {
            "id",
            "first_name",
            "last_name",
            "icon_url",
            "display_name",
            "is_office_staff",
            "is_workshop_staff",
        }
        assert row["icon_url"] is None
        assert row["display_name"] == "Req Ester"
