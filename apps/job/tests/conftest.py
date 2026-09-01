"""Shared fixtures for the job app's service and API tests."""

from collections.abc import Iterator
from decimal import Decimal

import pytest
from django.core.cache import cache
from django.test import Client

from apps.accounts.models import Staff
from apps.company.models import Company
from apps.company.tests.conftest import authenticate, make_company
from apps.company.tests.job_fixtures import make_job
from apps.job.models import Job

PASSWORD = "s3cret-Pass!"


@pytest.fixture(autouse=True)
def _clear_default_cache() -> Iterator[None]:
    """Isolate the event debounce/duplicate cache keys between tests."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def office_staff() -> Staff:
    """An office staff member (may mutate jobs), with a configured wage rate.

    Time pricing refuses to cost a staff member with no wage rate, so every
    fixture that can book time carries one (base 40.00 + 20% labour cost loading =
    wage_rate 48.00).
    """
    return Staff.objects.create_user(
        office_email="job-office@example.com",
        password=PASSWORD,
        first_name="Office",
        last_name="Staff",
        is_office_staff=True,
        base_wage_rate=Decimal("40.00"),
    )


@pytest.fixture
def workshop_staff() -> Staff:
    """A non-office staff member (read-only on the job endpoints)."""
    return Staff.objects.create_user(
        office_email="job-workshop@example.com",
        password=PASSWORD,
        first_name="Workshop",
        last_name="Staff",
        is_office_staff=False,
        base_wage_rate=Decimal("40.00"),
    )


@pytest.fixture
def unpaid_staff() -> Staff:
    """A staff member whose wage rate was never configured (pricing must refuse)."""
    return Staff.objects.create_user(
        office_email="job-unpaid@example.com",
        password=PASSWORD,
        first_name="Unpriced",
        last_name="Person",
        is_office_staff=False,
    )


@pytest.fixture
def timesheet_worker() -> Staff:
    """A workshop worker with a known wage rate, for time-entry pricing tests.

    ``base_wage_rate`` 40.00 with the default 20% labour cost loading gives
    ``wage_rate`` 48.00; the root conftest provides the CompanyDefaults the
    loading calculation and the default-subtype assignment need.
    """
    return Staff.objects.create_user(
        office_email="job-timesheet-worker@example.com",
        password=PASSWORD,
        first_name="Tina",
        last_name="Worker",
        is_office_staff=False,
        base_wage_rate=Decimal("40.00"),
    )


@pytest.fixture
def client(office_staff: Staff) -> Client:
    """A django test client authenticated as office staff."""
    client = Client()
    authenticate(client, office_staff)
    return client


@pytest.fixture
def company() -> Company:
    """A company allowed to hold jobs, with the job prerequisites seeded."""
    return make_company("Job Test Company")


@pytest.fixture
def job(company: Company, office_staff: Staff) -> Job:
    """A job created through the real save path."""
    return make_job(company, office_staff, name="Fixture Job")
