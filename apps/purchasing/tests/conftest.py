"""Shared fixtures for the purchasing app's service and API tests."""

from decimal import Decimal

import pytest
from django.test import Client

from apps.accounts.models import Staff
from apps.company.models import Company
from apps.company.tests.conftest import authenticate, make_company
from apps.company.tests.job_fixtures import make_job, seed_job_prereqs
from apps.core.models import CompanyDefaults
from apps.job.models import Job
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLine, Stock

PASSWORD = "s3cret-Pass!"


@pytest.fixture(autouse=True)
def _reset_stock_holding_cache() -> None:
    """Stock caches the stock-holding job on the class; tests get fresh rows."""
    Stock._stock_holding_job = None


@pytest.fixture
def office_staff() -> Staff:
    """An office staff member with a wage rate (job saves need one)."""
    seed_job_prereqs()
    return Staff.objects.create_user(
        email="purchasing-office@example.com",
        password=PASSWORD,
        first_name="Olive",
        last_name="Office",
        is_office_staff=True,
        base_wage_rate=Decimal("40.00"),
    )


@pytest.fixture
def workshop_staff() -> Staff:
    """A non-office staff member (purchasing endpoints accept any staff)."""
    seed_job_prereqs()
    return Staff.objects.create_user(
        email="purchasing-workshop@example.com",
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
    seed_job_prereqs()
    return make_company("Purchasing Test Company")


@pytest.fixture
def supplier() -> Company:
    """A supplier company with an email (the PO email endpoint needs one)."""
    seed_job_prereqs()
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
    seed_job_prereqs()
    defaults = CompanyDefaults.get_solo()
    defaults.materials_markup = Decimal("0.20")
    defaults.save()
    return defaults


def make_purchase_order(
    *,
    supplier: Company | None = None,
    created_by: Staff | None = None,
    status: str = "draft",
    reference: str | None = None,
) -> PurchaseOrder:
    """Create a PO through the real save path (the model numbers it)."""
    return PurchaseOrder.objects.create(
        supplier=supplier, created_by=created_by, status=status, reference=reference
    )


def make_po_line(  # noqa: PLR0913 -- a factory: every field is an axis a test varies
    po: PurchaseOrder,
    *,
    description: str = "Test line",
    quantity: str = "10.00",
    unit_cost: str | None = "25.00",
    job: Job | None = None,
    item_code: str | None = None,
    **extra: object,
) -> PurchaseOrderLine:
    """Create a PO line with sensible defaults."""
    return PurchaseOrderLine.objects.create(
        purchase_order=po,
        description=description,
        quantity=Decimal(quantity),
        unit_cost=Decimal(unit_cost) if unit_cost is not None else None,
        job=job,
        item_code=item_code,
        **extra,
    )


def make_stock(
    job: Job,
    *,
    description: str = "Stock item",
    quantity: str = "10.00",
    unit_cost: str = "25.00",
    source: str = "manual",
    **extra: object,
) -> Stock:
    """Create a Stock row through the real save path."""
    return Stock.objects.create(
        job=job,
        description=description,
        quantity=Decimal(quantity),
        unit_cost=Decimal(unit_cost),
        source=source,
        **extra,
    )
