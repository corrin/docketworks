"""Shared fixtures for the accounting report API tests."""

import pytest
from django.test import Client

from apps.accounts.models import Staff
from apps.company.tests.conftest import PASSWORD, authenticate


def make_staff(email: str, **extra: object) -> Staff:
    """An ordinary authenticated staff member — v1 gated every report on
    plain IsAuthenticated, so no office/superuser flags are needed."""
    return Staff.objects.create_user(
        email=email,
        password=PASSWORD,
        first_name=str(extra.pop("first_name", "Report")),
        last_name=str(extra.pop("last_name", "Reader")),
        **extra,
    )


@pytest.fixture
def staff() -> Staff:
    return make_staff("reports@example.com")


@pytest.fixture
def authenticated_client(staff: Staff) -> Client:
    client = Client()
    authenticate(client, staff)
    return client
