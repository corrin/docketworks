"""Labour-cost loading changes keep every stored Staff wage rate coherent."""

from decimal import Decimal

import pytest
from django.utils import timezone

from apps.accounts.models import Staff
from apps.core.models import CompanyDefaults

pytestmark = pytest.mark.django_db


def _paid_staff(email: str = "loading@example.test") -> Staff:
    return Staff.objects.create_user(
        office_email=email,
        password=None,
        first_name="Load",
        last_name="Test",
        base_wage_rate=Decimal("33.40"),
    )


def test_explicit_loading_save_recomputes_staff_wage_rates() -> None:
    """A real settings edit must still propagate the new costing rate."""
    staff = _paid_staff()
    defaults = CompanyDefaults.get_solo()
    defaults.labour_cost_loading = Decimal("23.00")

    defaults.save(update_fields=["labour_cost_loading"])

    staff.refresh_from_db()
    assert staff.wage_rate == Decimal("41.08")


def test_unrelated_partial_save_cannot_recompute_from_a_stale_loading() -> None:
    """A sync cursor save must not turn an out-of-date instance into a settings edit."""
    defaults = CompanyDefaults.get_solo()
    defaults.labour_cost_loading = Decimal("20.00")
    defaults.save(update_fields=["labour_cost_loading"])
    staff = _paid_staff()
    stale_defaults = CompanyDefaults.get_solo()

    current_defaults = CompanyDefaults.get_solo()
    current_defaults.labour_cost_loading = Decimal("23.00")
    current_defaults.save(update_fields=["labour_cost_loading"])
    staff.refresh_from_db()
    correctly_loaded_rate = staff.wage_rate
    correctly_loaded_at = staff.updated_at

    stale_defaults.last_xero_sync = timezone.now()
    stale_defaults.save(update_fields=["last_xero_sync"])

    staff.refresh_from_db()
    assert CompanyDefaults.get_solo().labour_cost_loading == Decimal("23.00")
    assert staff.wage_rate == correctly_loaded_rate == Decimal("41.08")
    assert staff.updated_at == correctly_loaded_at
