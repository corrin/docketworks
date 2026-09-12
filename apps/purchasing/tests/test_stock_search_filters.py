"""The count picker must apply eligibility before ranking and pagination."""

import pytest
from django.test import Client

from apps.job.models import Job
from apps.purchasing.models import StockMovement
from apps.purchasing.tests.factories import make_stock

pytestmark = pytest.mark.django_db


def test_countable_search_excludes_ineligible_rows_before_pagination(
    api: Client, stock_holding_job: Job, job: Job
) -> None:
    """Filtering a page after ranking can hide eligible stock behind catalogue matches."""
    eligible = make_stock(stock_holding_job, description="50x50 galvanised SHS", quantity="0")
    make_stock(stock_holding_job, description=eligible.description, source="product_catalog")
    make_stock(stock_holding_job, description=eligible.description, is_active=False)
    make_stock(job, description=eligible.description)
    response = api.get(
        "/api/purchasing/stock/search/",
        {"q": "50x50 SHS galv", "countable": "true", "page_size": "1"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["results"][0]["id"] == str(eligible.id)
    assert body["results"][0]["can_count"] is True
    assert body["results"][0]["can_retire"] is True
    assert body["results"][0]["inventory_version"] == eligible.inventory_version


def test_stock_search_can_retrieve_inactive_identity_without_making_it_countable(
    api: Client, stock_holding_job: Job
) -> None:
    """History navigation must find retired identities without offering a new count."""
    stock = make_stock(stock_holding_job, is_active=False, location="Rack 2")
    response = api.get(
        "/api/purchasing/stock/search/",
        {"include_inactive": "true", "stock_ids": [str(stock.id)], "location": "Rack 2"},
    )
    assert response.status_code == 200
    rows = response.json()["results"]
    assert len(rows) == 1
    assert rows[0]["id"] == str(stock.id)
    assert rows[0]["can_count"] is False
    assert rows[0]["can_retire"] is False


def test_stock_list_returns_the_same_bounded_search_envelope(
    api: Client, stock_holding_job: Job
) -> None:
    """The stock page must not download every row while the picker pages the same data."""
    ids = [
        str(make_stock(stock_holding_job, description=f"Paged material {index}").id)
        for index in range(3)
    ]
    query = {"stock_ids": ids, "page_size": "2"}
    first = api.get("/api/purchasing/stock/", query).json()
    second = api.get("/api/purchasing/stock/", {**query, "page": "2"}).json()
    assert first["count"] == 3
    assert first["page_size"] == 2
    assert first["total_pages"] == 2
    assert [row["id"] for row in first["results"] + second["results"]] == ids
    assert api.get("/api/purchasing/stock/", {**query, "page": "3"}).status_code == 404


def test_movement_history_is_bounded_and_retired_stock_remains_readable(
    api: Client, stock_holding_job: Job
) -> None:
    """A retired item's accumulated evidence must stay accessible one page at a time."""
    stock = make_stock(stock_holding_job, quantity="0", is_active=False)
    movements = StockMovement.objects.bulk_create(
        [
            StockMovement(
                stock=stock,
                kind="receipt",
                quantity_before=0,
                quantity_after=0,
                quantity_change=0,
                unit_cost=25,
                reason=f"Historical receipt {index}",
            )
            for index in range(3)
        ]
    )
    endpoint = f"/api/purchasing/stock/{stock.id}/movements/"
    first = api.get(endpoint, {"page_size": 2}).json()
    second = api.get(endpoint, {"page_size": 2, "page": 2}).json()
    assert first["count"] == 3
    assert first["page_size"] == 2
    assert len(first["results"]) == 2
    assert {row["id"] for row in first["results"] + second["results"]} == {
        str(movement.id) for movement in movements
    }
    assert api.get(endpoint, {"page_size": 2, "page": 3}).status_code == 404
