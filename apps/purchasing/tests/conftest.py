"""Shared fixtures for the purchasing app's service and API tests."""

from decimal import Decimal

import pytest
from django.test import Client

from apps.accounts.models import Staff
from apps.company.models import Company
from apps.company.tests.conftest import authenticate, make_company
from apps.company.tests.job_fixtures import make_job
from apps.core.models import CompanyDefaults
from apps.job.models import Job
from apps.purchasing.models import Stock

PASSWORD = "s3cret-Pass!"


@pytest.fixture(autouse=True)
def _reset_stock_holding_cache() -> None:
    """Stock caches the stock-holding job on the class; tests get fresh rows."""
    Stock._stock_holding_job = None


@pytest.fixture
def office_staff() -> Staff:
    """An office staff member with a wage rate (job saves need one)."""
    return Staff.objects.create_user(
        office_email="purchasing-office@example.com",
        password=PASSWORD,
        first_name="Olive",
        last_name="Office",
        is_office_staff=True,
        base_wage_rate=Decimal("40.00"),
    )


@pytest.fixture
def workshop_staff() -> Staff:
    """A non-office staff member (purchasing endpoints accept any staff)."""
    return Staff.objects.create_user(
        office_email="purchasing-workshop@example.com",
        password=PASSWORD,
        first_name="Wes",
        last_name="Workshop",
        is_office_staff=False,
        base_wage_rate=Decimal("40.00"),
    )


@pytest.fixture
def client(office_staff: Staff) -> Client:
    """A django test client authenticated as office staff."""
    test_client = Client()
    authenticate(test_client, office_staff)
    return test_client


@pytest.fixture
def company() -> Company:
    """A company allowed to hold jobs, with the job prerequisites seeded."""
    return make_company("Purchasing Test Company")


@pytest.fixture
def supplier() -> Company:
    """A supplier company with an email (the PO email endpoint needs one)."""
    return make_company("Metal Supplies Ltd", email="sales@metalsupplies.example", is_supplier=True)


@pytest.fixture
def job(company: Company, office_staff: Staff) -> Job:
    """A customer job created through the real save path."""
    return make_job(company, office_staff, name="Purchasing Fixture Job")


@pytest.fixture
def stock_holding_job(company: Company, office_staff: Staff) -> Job:
    """The job Stock.get_stock_holding_job() resolves to."""
    Stock._stock_holding_job = None
    return make_job(company, office_staff, name=Stock.STOCK_HOLDING_JOB_NAME)


@pytest.fixture
def company_defaults() -> CompanyDefaults:
    """The singleton, with a known materials markup for revenue assertions."""
    defaults = CompanyDefaults.get_solo()
    defaults.materials_markup = Decimal("0.20")
    defaults.save()
    return defaults
