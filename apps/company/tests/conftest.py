"""Shared fixtures for the company app's API and service tests."""

import pytest
from django.test import Client

from apps.accounts.models import Staff
from apps.accounts.tests.helpers import authenticate

PASSWORD = "s3cret-Pass!"


@pytest.fixture
def office_staff() -> Staff:
    """An office staff member (may use the people/data-quality endpoints)."""
    return Staff.objects.create_user(
        office_email="office@example.com",
        password=PASSWORD,
        first_name="Office",
        last_name="Staff",
        is_office_staff=True,
    )


@pytest.fixture
def workshop_staff() -> Staff:
    """A non-office staff member (rejected by office-only endpoints)."""
    return Staff.objects.create_user(
        office_email="workshop@example.com",
        password=PASSWORD,
        first_name="Workshop",
        last_name="Staff",
        is_office_staff=False,
    )


@pytest.fixture
def client(office_staff: Staff) -> Client:
    """A django test client authenticated as office staff."""
    client = Client()
    authenticate(client, office_staff)
    return client
