"""The SPA loads company defaults into a store on boot.

`JobViewTabs` renders `JobEstimateTab` only when the store is populated, so a
failure here darkens the whole job cluster rather than just the settings
screen. That is why these assert the update SEMANTICS, not just a 200.

It lives beside its endpoint. Both the singleton and an authenticated Staff
come from the root conftest by fixture NAME, so nothing here imports a domain
app and the layer contract is satisfied without moving the test away from the
code it tests.
"""

from decimal import Decimal

import pytest
from django.test import Client

from apps.core.api import CompanyDefaultsOut
from apps.core.models import CompanyDefaults

pytestmark = pytest.mark.django_db

URL = "/api/company-defaults/"


def test_requires_authentication(client: Client) -> None:
    """`client` is pytest-django's anonymous one; `api` is the authenticated fixture."""
    assert client.get(URL).status_code == 401


def test_schema_is_derived_from_the_model() -> None:
    """Every concrete column appears, minus the two write-only image fields.

    Asserted rather than assumed: a hand-listed schema is what lets a column
    and its wire shape drift apart, and 67 fields is far past where anyone
    notices one missing by reading.
    """
    columns = {
        field.name
        for field in CompanyDefaults._meta.get_fields()
        if hasattr(field, "attname") and field.name not in {"logo", "logo_wide"}
    }
    derived = set(CompanyDefaultsOut.model_fields) - {"logo_url", "logo_wide_url"}

    assert derived == columns


def test_retrieve_returns_the_singleton(api: Client) -> None:
    """The row exists without this test creating it — the baseline supplies it."""
    response = api.get(URL)

    assert response.status_code == 200
    assert response.json()["company_name"] == CompanyDefaults.get_solo().company_name


def test_logo_urls_are_null_when_no_logo_is_uploaded(api: Client) -> None:
    body = api.get(URL).json()

    assert body["logo_url"] is None
    assert body["logo_wide_url"] is None


def test_patch_applies_only_the_fields_sent(api: Client) -> None:
    """Omission must leave the stored value alone.

    The settings screen submits one section at a time, so a PATCH that reset
    unmentioned fields would silently wipe the rest of the configuration.
    """
    defaults = CompanyDefaults.get_solo()
    defaults.wage_rate = Decimal("42.00")
    defaults.save(update_fields=["wage_rate"])

    response = api.patch(URL, data={"company_name": "Renamed Ltd"}, content_type="application/json")

    assert response.status_code == 200
    defaults.refresh_from_db()
    assert defaults.company_name == "Renamed Ltd"
    assert defaults.wage_rate == Decimal("42.00")


def test_patch_returns_the_updated_singleton(api: Client) -> None:
    body = api.patch(
        URL, data={"company_name": "Renamed Ltd"}, content_type="application/json"
    ).json()

    assert body["company_name"] == "Renamed Ltd"


def test_patch_rejects_a_value_the_model_refuses(api: Client) -> None:
    """full_clean runs before save, so a bad value is a 4xx not a 500.

    Without it the write reaches the database and surfaces as an IntegrityError
    the caller cannot act on.
    """
    response = api.patch(URL, data={"company_name": ""}, content_type="application/json")

    assert response.status_code in {400, 422}
    assert CompanyDefaults.get_solo().company_name != ""
