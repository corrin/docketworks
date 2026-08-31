"""Shared fixtures for the company app's API and service tests."""

import pytest
from django.test import Client
from django.utils import timezone

from apps.accounts.models import Staff
from apps.company.models import Company
from apps.core.auth import issue_refresh_token

PASSWORD = "s3cret-Pass!"


def make_company(name: str, **kwargs: object) -> Company:
    """Create a Company with the only field the model truly requires."""
    defaults: dict[str, object] = {"xero_last_modified": timezone.now()}
    defaults.update(kwargs)
    return Company.objects.create(name=name, **defaults)


def authenticate(client: Client, staff: Staff) -> None:
    """Set the HttpOnly access-token cookie the way a logged-in browser has it.

    Through the one mint, not RefreshToken.for_user — issued tokens carry the
    password fingerprint, and a bare for_user token is rejected as stale.
    """
    refresh = issue_refresh_token(staff)
    client.cookies["access_token"] = str(refresh.access_token)


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
