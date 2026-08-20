"""Shared fixtures for the accounting report API tests."""

import pytest
from django.test import Client

from apps.accounts.models import Staff
from apps.company.tests.conftest import authenticate
from apps.timesheet.tests.conftest import make_staff


@pytest.fixture
def staff() -> Staff:
    """An office-staff member, which is what the reports require.

    Opus: `make_staff` defaults `is_office_staff` to False, and these tests
    read as authorisation evidence — so the flag is set explicitly here
    rather than left to a default that would silently re-open the gate if it
    ever changed.

    Reuses the timesheet make_staff (ADR 0039): its xero_user_id and
    explicit employment start also keeps the member visible to reports that
    filter through get_displayable_staff.
    """
    return make_staff("reports@example.com", is_office_staff=True)


@pytest.fixture
def authenticated_client(staff: Staff) -> Client:
    client = Client()
    authenticate(client, staff)
    return client


@pytest.fixture
def workshop_client() -> Client:
    """A logged-in staff member WITHOUT is_office_staff.

    The reports hide themselves from the navbar for this user; these tests
    exist because hiding a link is presentation, and the endpoint is the
    control.
    """
    client = Client()
    authenticate(client, make_staff("workshop@example.com"))
    return client
