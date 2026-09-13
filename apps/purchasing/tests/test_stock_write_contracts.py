"""Metadata endpoints must not masquerade as inventory posting workflows."""

import json

import pytest
from django.test import Client
from pydantic import JsonValue

from apps.job.models import Job
from apps.purchasing.models import Stock
from apps.purchasing.tests.factories import make_stock

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("field", ["quantity", "unit_cost", "source", "is_active", "unknown"])
@pytest.mark.parametrize("method", ["patch", "put"])
def test_metadata_refuses_inventory_fields_even_when_unchanged(
    api: Client, stock_holding_job: Job, field: str, method: str
) -> None:
    """Accepting matching values hides an unsupported write until a concurrent move occurs."""
    stock = make_stock(stock_holding_job, description="Original", quantity="0")
    values: dict[str, JsonValue] = {
        "quantity": "0",
        "unit_cost": "25",
        "source": "manual",
        "is_active": True,
        "unknown": "not metadata",
    }
    response = api.generic(
        method.upper(),
        f"/api/purchasing/stock/{stock.id}/",
        data=json.dumps({"description": "Changed", field: values[field]}),
        content_type="application/json",
    )
    assert response.status_code == 422
    stock.refresh_from_db()
    assert stock.description == "Original"


def test_creation_requires_a_cost_and_creates_only_an_empty_manual_identity(
    api: Client, stock_holding_job: Job
) -> None:
    """Found quantity must be posted in a count; creating an identity cannot invent provenance."""
    endpoint = "/api/purchasing/stock/"
    missing = api.post(endpoint, {"description": "Found plate"}, content_type="application/json")
    assert missing.status_code == 422
    created = api.post(
        endpoint,
        {"description": "Found plate", "unit_cost": "0"},
        content_type="application/json",
    )
    assert created.status_code == 201
    stock = Stock.objects.get(pk=created.json()["id"])
    assert stock.job == stock_holding_job
    assert stock.quantity == 0
    assert stock.unit_cost == 0
    assert stock.source == "manual"
    assert stock.is_active is True


@pytest.mark.parametrize(
    "data",
    [
        {"quantity": 1},
        {"source": "product_catalog"},
        {"is_active": False},
        {"unknown": "ignored"},
        {"unit_cost": -1},
        {"description": ""},
    ],
)
def test_identity_creation_refuses_unsupported_inventory_inputs(
    api: Client, data: dict[str, JsonValue]
) -> None:
    """Bad input must be refused before saving any stock or scheduling metadata parsing."""
    response = api.post(
        "/api/purchasing/stock/",
        {"description": "Plate", "unit_cost": 0, **data},
        content_type="application/json",
    )
    assert response.status_code == 422
    assert not Stock.objects.filter(description="Plate").exists()
