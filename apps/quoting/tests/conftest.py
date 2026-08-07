"""Shared fixtures for the quoting app's service and API tests."""

import json
from decimal import Decimal
from typing import Any

import pytest
from django.test import Client

from apps.accounts.models import Staff
from apps.ai.models import AIProvider
from apps.company.models import Company
from apps.company.tests.conftest import authenticate, make_company
from apps.quoting.models import SupplierPriceList, SupplierProduct

PASSWORD = "s3cret-Pass!"

# THE LLM BOUNDARY, named once (ADR 0039/0041). ``apps.ai``'s gateway is the
# only route to a model, and ``product_parser`` binds ``chat_completion`` at
# import, so this is where ``mock.patch`` must intercept it — patching
# ``apps.ai.services.llm_client.chat_completion`` would leave the already-bound
# reference untouched and silently call litellm for real. Every test in the
# repo that fakes a model reply uses this constant; nothing below it is ever
# mocked, so prompting, JSON extraction, mapping persistence and back-flow all
# run for real.
LLM_BOUNDARY = "apps.quoting.services.product_parser.chat_completion"


def llm_reply(*rows: dict[str, Any]) -> str:
    """Render a model reply carrying one parsed product per row, as the prompt asks.

    Every field the prompt names is present, defaulting to null, so a test only
    states the values it is actually about.
    """
    if not rows:
        raise ValueError("llm_reply needs at least one product row")
    payload = []
    for row in rows:
        product: dict[str, Any] = {
            "item_code": None,
            "description": None,
            "metal_type": None,
            "alloy": None,
            "specifics": None,
            "dimensions": None,
            "unit_cost": None,
            "price_unit": None,
            "confidence": 0.9,
        }
        unknown = set(row) - set(product)
        if unknown:
            raise ValueError(f"llm_reply got fields the prompt never asks for: {sorted(unknown)}")
        product.update(row)
        payload.append(product)
    return json.dumps(payload)


@pytest.fixture
def office_staff() -> Staff:
    """An office staff member — the quoting endpoints are office-only."""
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


def make_supplier_product(  # noqa: PLR0913 -- a factory: every field is an axis a test varies
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
