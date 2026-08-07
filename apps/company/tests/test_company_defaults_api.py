"""The SPA loads company defaults into a store on boot.

`JobViewTabs` renders `JobEstimateTab` only when the store is populated, so a
failure here darkens the whole job cluster rather than just the settings
screen. That is why these assert the update SEMANTICS, not just a 200.

The endpoint lives in `apps.core`; this test lives here because it cannot go
there. Seeding the singleton needs a real `Company` (shop_company is a NOT NULL
FK) and authenticating needs a `Staff`, and core sits BELOW the domain apps, so
importing either from `apps.core.tests` breaks the layer contract. `core`'s own
model dodges that with a string FK reference — a test cannot.
"""

from decimal import Decimal

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import Client

from apps.company.tests.conftest import make_company
from apps.core.api import CompanyDefaultsOut
from apps.core.models import CompanyDefaults

pytestmark = pytest.mark.django_db

URL = "/api/company-defaults/"


@pytest.fixture
def defaults() -> CompanyDefaults:
    """The singleton, seeded the way the data restore delivers it.

    It cannot be created on demand: shop_company is a NOT NULL FK with no
    default, so django-solo's get_solo() dies trying.
    """
    return CompanyDefaults.objects.create(
        company_name="Morris Sheetmetal", shop_company=make_company("Shop Company")
    )


def test_requires_authentication() -> None:
    """A bare Client, not this app's `client` fixture, which is authenticated."""
    assert Client().get(URL).status_code == 401


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


def test_missing_singleton_says_what_to_do(client: Client) -> None:
    """An unseeded install must not surface as an IntegrityError about a column.

    get_solo() would try to CREATE the row, and shop_company is NOT NULL with
    no default, so the caller got a 500 naming `shop_company_id` rather than
    the actual problem.
    """
    assert CompanyDefaults.objects.count() == 0

    response = client.get(URL)

    assert response.status_code == 500
    assert "data restore" in response.json()["detail"]


@pytest.mark.usefixtures("defaults")
def test_retrieve_returns_the_singleton(client: Client) -> None:
    response = client.get(URL)

    assert response.status_code == 200
    assert response.json()["company_name"] == "Morris Sheetmetal"


@pytest.mark.usefixtures("defaults")
def test_logo_urls_are_null_when_no_logo_is_uploaded(client: Client) -> None:
    body = client.get(URL).json()

    assert body["logo_url"] is None
    assert body["logo_wide_url"] is None


def test_patch_applies_only_the_fields_sent(client: Client, defaults: CompanyDefaults) -> None:
    """Omission must leave the stored value alone.

    The settings screen submits one section at a time, so a PATCH that reset
    unmentioned fields would silently wipe the rest of the configuration.
    """
    defaults.wage_rate = Decimal("42.00")
    defaults.save(update_fields=["wage_rate"])

    response = client.patch(
        URL, data={"company_name": "Renamed Ltd"}, content_type="application/json"
    )

    assert response.status_code == 200
    defaults.refresh_from_db()
    assert defaults.company_name == "Renamed Ltd"
    assert defaults.wage_rate == Decimal("42.00")


@pytest.mark.usefixtures("defaults")
def test_patch_returns_the_updated_singleton(client: Client) -> None:
    body = client.patch(
        URL, data={"company_name": "Renamed Ltd"}, content_type="application/json"
    ).json()

    assert body["company_name"] == "Renamed Ltd"


@pytest.mark.usefixtures("defaults")
def test_patch_rejects_a_value_the_model_refuses(client: Client) -> None:
    """full_clean runs before save, so a bad value is a 4xx not a 500.

    Without it the write reaches the database and surfaces as an IntegrityError
    the caller cannot act on.
    """
    response = client.patch(URL, data={"company_name": ""}, content_type="application/json")

    assert response.status_code in {400, 422}
    assert CompanyDefaults.get_solo().company_name != ""


def test_get_solo_never_creates() -> None:
    """The override is the whole point: reads do not write.

    django-solo ships get_solo as get_or_create, and ~12 services call it —
    several reached from GET report endpoints, so a plain report read would
    have created a row. That it happened to fail here on shop_company made it
    visible; silently succeeding would have been just as wrong.
    """
    assert CompanyDefaults.objects.count() == 0

    with pytest.raises(ImproperlyConfigured, match="data restore"):
        CompanyDefaults.get_solo()

    assert CompanyDefaults.objects.count() == 0
