"""Shared fixtures for the job app's service and API tests."""

from collections.abc import Iterator

import pytest
from django.core.cache import cache
from django.test import Client

from apps.accounts.models import Staff
from apps.company.models import Company
from apps.company.tests.conftest import authenticate, make_company
from apps.company.tests.job_fixtures import make_job, seed_job_prereqs
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
    """An office staff member (may mutate jobs)."""
    return Staff.objects.create_user(
        email="job-office@example.com",
        password=PASSWORD,
        first_name="Office",
        last_name="Staff",
        is_office_staff=True,
    )


@pytest.fixture
def workshop_staff() -> Staff:
    """A non-office staff member (read-only on the job endpoints)."""
    return Staff.objects.create_user(
        email="job-workshop@example.com",
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


@pytest.fixture
def company() -> Company:
    """A company allowed to hold jobs, with the job prerequisites seeded."""
    seed_job_prereqs()
    return make_company("Job Test Company")


@pytest.fixture
def job(company: Company, office_staff: Staff) -> Job:
    """A job created through the real save path."""
    return make_job(company, office_staff, name="Fixture Job")
