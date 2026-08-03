"""Shared fixtures for the quoting app's service and API tests."""

from decimal import Decimal

import pytest
from django.test import Client

from apps.accounts.models import Staff
from apps.ai.models import AIProvider
from apps.company.models import Company
from apps.company.tests.conftest import authenticate, make_company
from apps.company.tests.job_fixtures import seed_job_prereqs
from apps.quoting.models import SupplierPriceList, SupplierProduct

PASSWORD = "s3cret-Pass!"


@pytest.fixture
def office_staff() -> Staff:
    """An office staff member — the quoting endpoints are office-only."""
    seed_job_prereqs()
    return Staff.objects.create_user(
        email="quoting-office@example.com",
        password=PASSWORD,
        first_name="Olive",
        last_name="Office",
        is_office_staff=True,
        base_wage_rate=Decimal("40.00"),
    )


@pytest.fixture
def workshop_staff() -> Staff:
    """A non-office staff member (rejected by the quoting router's auth)."""
    seed_job_prereqs()
    return Staff.objects.create_user(
        email="quoting-workshop@example.com",
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
def supplier() -> Company:
    """A supplier company to hang price lists and products off."""
    seed_job_prereqs()
    return make_company("Steel & Tube", is_supplier=True)


@pytest.fixture
def gemini_provider() -> AIProvider:
    """A configured default Gemini provider (what the parser resolves)."""
    return AIProvider.objects.create(
        name="Gemini Flash",
        api_key="test-key",
        model_name="gemini-flash-latest",
        provider_type="Gemini",
        default=True,
    )


def make_price_list(supplier: Company, file_name: str = "prices.pdf") -> SupplierPriceList:
    """Create a price list for a supplier."""
    return SupplierPriceList.objects.create(supplier=supplier, file_name=file_name)


def make_supplier_product(
    supplier: Company,
    price_list: SupplierPriceList,
    *,
    product_name: str = "50x50x3 SHS",
    item_no: str = "SHS-50",
    variant_id: str = "v1",
    url: str = "https://example.test/shs-50",
    description: str | None = None,
    **extra: object,
) -> SupplierProduct:
    """Create a scraped supplier product row."""
    return SupplierProduct.objects.create(
        supplier=supplier,
        price_list=price_list,
        product_name=product_name,
        item_no=item_no,
        variant_id=variant_id,
        url=url,
        description=description,
        **extra,
    )
