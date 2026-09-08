"""Shared fixtures for the purchasing app's service and API tests."""

from decimal import Decimal

import pytest

from apps.accounts.models import Staff
from apps.company.models import Company
from apps.company.tests.factories import make_company
from apps.core.models import CompanyDefaults
from apps.purchasing.models import Stock

PASSWORD = "s3cret-Pass!"


@pytest.fixture(autouse=True)
def _reset_stock_holding_cache() -> None:
    """Stock caches the stock-holding job on the class; tests get fresh rows."""
    Stock._stock_holding_job = None


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
def supplier() -> Company:
    """A supplier company with an email (the PO email endpoint needs one)."""
    return make_company("Metal Supplies Ltd", email="sales@metalsupplies.example", is_supplier=True)


@pytest.fixture
def company_defaults() -> CompanyDefaults:
    """The singleton, with a known materials markup for revenue assertions."""
    defaults = CompanyDefaults.get_solo()
    defaults.materials_markup = Decimal("0.20")
    defaults.save()
    return defaults
