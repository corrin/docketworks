"""A store loads pay items on every page, so their absence blocks every spec.

The shape matters as much as the presence: v1's client is typed for a bare
array of ten fields, and the timesheet UI discriminates leave types from
earnings rates on `multiplier` being null.
"""

from decimal import Decimal

import pytest
from django.test import Client

from apps.accounts.models import Staff
from apps.company.tests.conftest import authenticate
from apps.xero.models import XeroPayItem

pytestmark = pytest.mark.django_db

URL = "/api/xero/pay-items/"


@pytest.fixture
def api(client: Client) -> Client:
    staff = Staff.objects.create_user(
        email="xero-office@example.com",
        password="s3cret-Pass!",
        first_name="Office",
        last_name="Staff",
        is_office_staff=True,
    )
    authenticate(client, staff)
    return client


def test_requires_authentication(client: Client) -> None:
    assert client.get(URL).status_code == 401


def test_returns_a_bare_array_not_a_paginated_envelope(api: Client) -> None:
    """v1's client is typed `z.array(XeroPayItem)`; an envelope would break it."""
    response = api.get(URL)

    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_leave_types_and_earnings_rates_are_distinguishable(api: Client) -> None:
    """`multiplier` null is how the timesheet UI tells the two apart."""
    XeroPayItem.objects.create(name="Annual Leave", uses_leave_api=True, multiplier=None)
    XeroPayItem.objects.create(
        name="Ordinary Time", uses_leave_api=False, multiplier=Decimal("1.00")
    )

    by_name = {row["name"]: row for row in api.get(URL).json()}

    assert by_name["Annual Leave"]["uses_leave_api"] is True
    assert by_name["Annual Leave"]["multiplier"] is None
    assert by_name["Ordinary Time"]["uses_leave_api"] is False
    assert by_name["Ordinary Time"]["multiplier"] == 1.0


def test_carries_every_field_the_client_expects(api: Client) -> None:
    """Ten fields, from v1's generated zod schema. A missing one is a runtime
    validation failure in the SPA, not a type error at build."""
    XeroPayItem.objects.create(
        name="Ordinary Time", uses_leave_api=False, multiplier=Decimal("1.00")
    )

    row = api.get(URL).json()[0]

    assert set(row) == {
        "id",
        "xero_id",
        "xero_tenant_id",
        "name",
        "uses_leave_api",
        "multiplier",
        "xero_last_modified",
        "xero_last_synced",
        "created_at",
        "updated_at",
    }


def test_unsynced_items_still_serialise(api: Client) -> None:
    """A restore brings rows in with no Xero ids until the tenant connects."""
    XeroPayItem.objects.create(
        name="Ordinary Time", uses_leave_api=False, multiplier=Decimal("1.00"), xero_id=None
    )

    row = api.get(URL).json()[0]

    assert row["xero_id"] is None
    assert row["name"] == "Ordinary Time"
