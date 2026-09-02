"""API tests for the staff admin list: GET /api/accounts/staff/.

The list is the whole staff table (departed members included — the admin
screen and the wage-loading checks read them), unlike the timesheet's
date-scoped displayable subset. Wage data makes it superuser surface.
"""

from datetime import date
from decimal import Decimal

import pytest
from django.test import Client

from apps.accounts.models import Staff
from apps.company.tests.conftest import authenticate

pytestmark = [
    pytest.mark.django_db,
    pytest.mark.urls("apps.accounts.tests.urls"),
]

URL = "/api/accounts/staff/"
PASSWORD = "s3cret-Pass!"


def make_staff(email: str, **extra: object) -> Staff:
    return Staff.objects.create_user(
        office_email=email,
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
    def test_office_staff_are_not_enough(self) -> None:
        office = make_staff("office@example.com", is_office_staff=True)
        assert client_for(office).get(URL).status_code == 403

    def test_anonymous_is_rejected(self) -> None:
        assert Client().get(URL).status_code == 401


class TestList:
    def test_lists_every_staff_member_including_departed(self) -> None:
        superuser = make_staff("super@example.com", is_superuser=True, is_office_staff=True)
        make_staff("current@example.com", first_name="Cara", base_wage_rate=Decimal("40.00"))
        make_staff(
            "departed@example.com",
            first_name="Dee",
            date_left=date(2025, 12, 31),
            base_wage_rate=Decimal("30.00"),
        )

        response = client_for(superuser).get(URL)

        assert response.status_code == 200
        body = response.json()
        by_email = {row["office_email"]: row for row in body}
        # Containment, not equality: global fixtures may seed system staff rows.
        assert {"super@example.com", "current@example.com", "departed@example.com"} <= set(by_email)
        assert by_email["departed@example.com"]["date_left"] == "2025-12-31"
        assert by_email["current@example.com"]["date_left"] is None
        assert by_email["current@example.com"]["is_office_staff"] is False

    def test_wage_rate_is_the_loaded_rate(self) -> None:
        """wage_rate carries the labour-cost-loaded rate the model computes on save."""
        superuser = make_staff("super@example.com", is_superuser=True, is_office_staff=True)
        worker = make_staff("paid@example.com", base_wage_rate=Decimal("40.00"))
        worker.refresh_from_db()
        assert worker.wage_rate > worker.base_wage_rate  # loading > 0 in the fixture defaults

        body = client_for(superuser).get(URL).json()

        row = next(item for item in body if item["office_email"] == "paid@example.com")
        # str() first: the wire carries JSON numbers (ADR 0046), and
        # Decimal(float) would materialise binary representation error.
        assert Decimal(str(row["base_wage_rate"])) == Decimal("40.00")
        assert Decimal(str(row["wage_rate"])) == worker.wage_rate
