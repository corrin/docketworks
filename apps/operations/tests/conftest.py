"""Fixtures for the operations app's API tests.

Reuses the company app's staff/company helpers rather than growing a parallel
set (ADR 0039) — these tests need an authenticated client and a company, both
of which already have one canonical builder.
"""

import pytest
from django.test import Client

from apps.accounts.models import Staff
from apps.company.models import Company
from apps.company.tests.conftest import authenticate, make_company


@pytest.fixture
def office_staff() -> Staff:
    """An authenticated-capable office staff member."""
    return Staff.objects.create_user(
        office_email="operations-office@example.com",
        password="s3cret-Pass!",
        first_name="Office",
        last_name="Staff",
        is_office_staff=True,
    )


@pytest.fixture
def company() -> Company:
    return make_company("Acme Ltd")


@pytest.fixture
def api(client: Client, office_staff: Staff) -> Client:
    """A client carrying the HttpOnly access-token cookie a browser would."""
    authenticate(client, office_staff)
    return client
