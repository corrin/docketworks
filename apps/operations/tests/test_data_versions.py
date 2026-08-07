"""The SPA polls /api/data-versions/ on every tab-focus to invalidate caches.

A version string that fails to change is the dangerous failure: the client
keeps serving data it believes is current, and nothing anywhere reports an
error. Every test here therefore asserts a version MOVED after a change, not
merely that the endpoint answered.
"""

from decimal import Decimal

import pytest
from django.test import Client

from apps.company.models import Company
from apps.operations.api import DATASET_VERSION_PROVIDERS, DataVersions
from apps.purchasing.models import Stock

pytestmark = pytest.mark.django_db

URL = "/api/data-versions/"


def _versions(client: Client) -> dict[str, str]:
    response = client.get(URL)
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, dict)
    return body


def test_every_provider_has_a_declared_field() -> None:
    """The dict and the response schema must not drift apart.

    Nothing at runtime checks them against each other: a provider added without
    its field would be silently dropped from the response by ninja, and a field
    without a provider would fail validation on every request.
    """
    assert set(DATASET_VERSION_PROVIDERS) == set(DataVersions.model_fields)


def test_requires_authentication(client: Client) -> None:
    assert client.get(URL).status_code == 401


def test_returns_a_version_for_every_dataset(api: Client) -> None:
    body = _versions(api)

    assert set(body) == set(DATASET_VERSION_PROVIDERS)
    assert all(isinstance(value, str) and value for value in body.values())


def test_response_is_not_cacheable(api: Client) -> None:
    """A cached copy defeats the endpoint's only purpose."""
    assert api.get(URL).headers["Cache-Control"] == "no-store"


def test_stock_version_moves_when_stock_changes(api: Client) -> None:
    before = _versions(api)["stock"]

    Stock.objects.create(
        description="Sheet 3mm", quantity=Decimal("1"), unit_cost=Decimal("2"), source="manual"
    )

    assert _versions(api)["stock"] != before


def test_stock_version_moves_on_deletion(api: Client) -> None:
    """The count exists for exactly this case.

    Deleting the newest row leaves Max(updated_at) pointing at an older one, so
    a timestamp-only version would tell the client nothing had changed.
    """
    item = Stock.objects.create(
        description="Sheet 3mm", quantity=Decimal("1"), unit_cost=Decimal("2"), source="manual"
    )
    Stock.objects.create(
        description="Bar 10mm", quantity=Decimal("1"), unit_cost=Decimal("3"), source="manual"
    )
    before = _versions(api)["stock"]

    item.delete()

    assert _versions(api)["stock"] != before


def test_kanban_related_moves_when_a_company_is_renamed(api: Client, company: Company) -> None:
    """A rename changes no Job row but does change what a Kanban card shows."""
    before = _versions(api)["kanban_related"]

    company.name = "Renamed Ltd"
    company.save(update_fields=["name", "django_updated_at"])

    assert _versions(api)["kanban_related"] != before


def test_datasets_move_independently(api: Client) -> None:
    """A change in one dataset must not invalidate the others.

    Otherwise the endpoint degrades into a single global version and the SPA
    refetches everything on any write, which is what it exists to avoid.
    """
    before = _versions(api)

    Stock.objects.create(
        description="Sheet 3mm", quantity=Decimal("1"), unit_cost=Decimal("2"), source="manual"
    )
    after = _versions(api)

    assert after["stock"] != before["stock"]
    assert after["kanban"] == before["kanban"]
    assert after["crm_calls"] == before["crm_calls"]
