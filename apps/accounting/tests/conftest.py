"""Shared fixtures for the accounting report API tests."""

import pytest
from django.test import Client

from apps.accounts.models import Staff
from apps.company.tests.conftest import authenticate
from apps.timesheet.tests.conftest import make_staff


@pytest.fixture
def staff() -> Staff:
    """An ordinary authenticated staff member — v1 gated every report on
    plain IsAuthenticated, so no office/superuser flags are needed.

    Reuses the timesheet make_staff (ADR 0039): its xero_user_id and
    backdated date_joined also keep the member visible to the reports that
    filter through get_displayable_staff.
    """
    return make_staff("reports@example.com")


@pytest.fixture
def authenticated_client(staff: Staff) -> Client:
    client = Client()
    authenticate(client, staff)
    return client
