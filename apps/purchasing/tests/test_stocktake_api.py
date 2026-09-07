"""Physical observations must reconcile inventory without erasing its history."""

from decimal import Decimal
from uuid import uuid4

import pytest
from django.db import DatabaseError, transaction
from django.test import Client

from apps.accounts.models import Staff
from apps.job.models import Job
from apps.job.models.costing import CostLine
from apps.purchasing.models import Stock, StockMovement, Stocktake, StocktakeConfiguration
from apps.purchasing.services.stock_movement_service import (
    MovementContext,
    inventory_difference,
    move_stock,
)
from apps.purchasing.services.stock_service import consume_stock
from apps.purchasing.tests.conftest import make_stock

pytestmark = pytest.mark.django_db
URL = "/api/purchasing/stocktakes/"


def start_count(client: Client, stock: Stock) -> str:
    response = client.post(f"{URL}setup/")
    assert response.status_code == 200, response.content
    response = client.post(URL, {"stock_id": str(stock.id)}, content_type="application/json")
    assert response.status_code == 200, response.content
    return str(response.json()["id"])


def save_count(client: Client, count_id: str, stock: Stock, counted: str | None) -> int:
    body = client.get(f"{URL}{count_id}/").json()
    line = body["lines"][0]
    response = client.put(
        f"{URL}{count_id}/",
        {
            "version": body["version"],
            "lines": [
                {
                    "id": line["id"],
                    "stock_id": str(stock.id),
                    "description": stock.description,
                    "location": stock.location,
                    "expected_quantity": line["expected_quantity"],
                    "expected_version": line["expected_version"],
                    "unit_cost": str(stock.unit_cost),
                    "counted_quantity": counted,
                    "reason": "Unexplained count difference",
                }
            ],
        },
        content_type="application/json",
    )
    assert response.status_code == 200, response.content
    return int(response.json()["version"])


@pytest.mark.parametrize(
    ("recorded", "counted"), [("0", "1"), ("1", "0"), ("-1", "0"), ("2", "0.125"), ("1", "1")]
)
def test_count_balances_workshop_and_adjustment_job(
    client: Client,
    stock_holding_job: Job,
    recorded: str,
    counted: str,
) -> None:
    stock = make_stock(stock_holding_job, quantity="0", unit_cost="80")
    move_stock(stock, Decimal(recorded), MovementContext(kind="opening", reason="Test opening"))
    count_id = start_count(client, stock)
    version = save_count(client, count_id, stock, counted)
    response = client.post(
        f"{URL}{count_id}/post/", {"version": version}, content_type="application/json"
    )
    assert response.status_code == 200, response.content
    stock.refresh_from_db()
    assert stock.quantity == Decimal(counted)
    assert inventory_difference(stock) == 0
    movements = StockMovement.objects.filter(stock=stock, kind="stocktake")
    difference = Decimal(counted) - Decimal(recorded)
    if difference == 0:
        assert not movements.exists()
    else:
        movement = movements.get()
        assert movement.quantity_change == difference
        assert movement.cost_line is not None
        assert movement.cost_line.quantity == -difference
        assert movement.cost_line.total_cost == -difference * 80
        assert movement.cost_line.unit_rev == 0
    retry = client.post(
        f"{URL}{count_id}/post/", {"version": version}, content_type="application/json"
    )
    assert retry.status_code == 200, retry.content
    stock.refresh_from_db()
    assert stock.quantity == Decimal(counted)


def test_blank_count_does_not_write_stock(client: Client, stock_holding_job: Job) -> None:
    stock = make_stock(stock_holding_job)
    count_id = start_count(client, stock)
    version = save_count(client, count_id, stock, None)
    response = client.post(
        f"{URL}{count_id}/post/", {"version": version}, content_type="application/json"
    )
    assert response.status_code == 400
    stock.refresh_from_db()
    assert stock.quantity == 10
    assert not stock.movements.exists()


def test_intervening_issue_requires_recount(
    client: Client,
    stock_holding_job: Job,
    job: Job,
    office_staff: Staff,
) -> None:
    stock = make_stock(stock_holding_job)
    count_id = start_count(client, stock)
    version = save_count(client, count_id, stock, "8")
    consume_stock(item=stock, job=job, qty=Decimal("2"), user=office_staff)
    response = client.post(
        f"{URL}{count_id}/post/", {"version": version}, content_type="application/json"
    )
    assert response.status_code == 400
    assert "recount" in response.json()["detail"]
    assert Stocktake.objects.get(pk=count_id).posted_at is None
    assert not StockMovement.objects.filter(kind="stocktake").exists()


def test_new_material_requires_cost_and_is_created_only_on_post(
    client: Client,
    stock_holding_job: Job,
) -> None:
    stock = make_stock(stock_holding_job)
    count_id = start_count(client, stock)
    line = {
        "id": str(uuid4()),
        "stock_id": None,
        "description": "Found 0.6mm sheet",
        "location": "Rack 3",
        "expected_quantity": 0,
        "expected_version": 0,
        "counted_quantity": 1,
        "reason": "Unexplained surplus",
    }
    response = client.put(
        f"{URL}{count_id}/", {"version": 0, "lines": [line]}, content_type="application/json"
    )
    assert response.status_code == 422
    line["unit_cost"] = 80
    response = client.put(
        f"{URL}{count_id}/", {"version": 0, "lines": [line]}, content_type="application/json"
    )
    assert response.status_code == 200, response.content
    assert not Stock.objects.filter(description=line["description"]).exists()
    response = client.post(
        f"{URL}{count_id}/post/", {"version": 1}, content_type="application/json"
    )
    assert response.status_code == 200, response.content
    found = Stock.objects.get(description=line["description"])
    assert found.quantity == 1
    assert found.job_id == stock_holding_job.id
    assert inventory_difference(found) == 0


def test_setup_is_explicit_and_idempotent(client: Client) -> None:
    assert client.get(f"{URL}setup/").json()["adjustment_job_id"] is None
    assert not StocktakeConfiguration.objects.exists()
    first = client.post(f"{URL}setup/")
    assert first.status_code == 200, first.content
    assert client.post(f"{URL}setup/").json() == first.json()
    assert StocktakeConfiguration.objects.count() == 1
    assert StocktakeConfiguration.objects.get().adjustment_job.shop_job


def test_correction_retains_original_posting(client: Client, stock_holding_job: Job) -> None:
    stock = make_stock(stock_holding_job, quantity="0")
    original = start_count(client, stock)
    version = save_count(client, original, stock, "1")
    assert (
        client.post(
            f"{URL}{original}/post/", {"version": version}, content_type="application/json"
        ).status_code
        == 200
    )
    response = client.post(f"{URL}{original}/correct/")
    assert response.status_code == 200, response.content
    correction = response.json()
    assert correction["corrects_id"] == original
    stock.refresh_from_db()
    version = save_count(client, correction["id"], stock, "0")
    assert (
        client.post(
            f"{URL}{correction['id']}/post/", {"version": version}, content_type="application/json"
        ).status_code
        == 200
    )
    stock.refresh_from_db()
    assert stock.quantity == 0
    assert StockMovement.objects.filter(stock=stock, kind="stocktake").count() == 2
    assert (
        client.put(
            f"{URL}{original}/", {"version": 2, "lines": []}, content_type="application/json"
        ).status_code
        == 400
    )


def test_failed_post_rolls_back_every_line(client: Client, stock_holding_job: Job) -> None:
    stock = make_stock(stock_holding_job, quantity="0")
    count_id = start_count(client, stock)
    body = client.get(f"{URL}{count_id}/").json()
    line = body["lines"][0]
    first = {
        "id": line["id"],
        "stock_id": str(stock.id),
        "description": stock.description,
        "location": None,
        "expected_quantity": 0,
        "expected_version": 0,
        "counted_quantity": 1,
        "unit_cost": 25,
        "reason": "Found stock",
    }
    second = dict(first, id=str(uuid4()), stock_id=None, description="Missing reason", reason=None)
    saved = client.put(
        f"{URL}{count_id}/",
        {"version": 0, "lines": [first, second]},
        content_type="application/json",
    )
    assert saved.status_code == 200, saved.content
    result = client.post(f"{URL}{count_id}/post/", {"version": 1}, content_type="application/json")
    assert result.status_code == 400
    stock.refresh_from_db()
    assert stock.quantity == 0
    assert not StockMovement.objects.filter(kind="stocktake").exists()
    assert not Stock.objects.filter(description="Missing reason").exists()


def test_quantity_edits_and_retirement_cannot_hide_stock(
    client: Client, stock_holding_job: Job
) -> None:
    stock = make_stock(stock_holding_job, quantity="2")
    path = f"/api/purchasing/stock/{stock.id}/"
    assert client.patch(path, {"quantity": 0}, content_type="application/json").status_code == 400
    assert client.delete(path).status_code == 400
    stock.refresh_from_db()
    assert stock.quantity == 2
    assert stock.is_active


def test_return_issue_credits_job_without_erasing_original(
    client: Client,
    stock_holding_job: Job,
    job: Job,
    office_staff: Staff,
) -> None:
    stock = make_stock(stock_holding_job, quantity="0")
    line = consume_stock(item=stock, job=job, qty=Decimal("1"), user=office_staff)
    movement = StockMovement.objects.get(cost_line=line)
    endpoint = f"/api/purchasing/stock-movements/{movement.id}/return/"
    result = client.post(endpoint)
    assert result.status_code == 200, result.content
    assert client.post(endpoint).json()["id"] == result.json()["id"]
    stock.refresh_from_db()
    assert stock.quantity == 0
    line.refresh_from_db()
    assert line.quantity == 1
    credit = StockMovement.objects.get(reverses=movement).cost_line
    assert credit is not None
    assert credit.quantity == -1
    assert credit.unit_cost == line.unit_cost


def test_count_picker_includes_zero_and_retired_workshop_material_only(
    client: Client,
    stock_holding_job: Job,
    job: Job,
) -> None:
    zero = make_stock(
        stock_holding_job, description="Countable sheet", quantity="0", is_active=False
    )
    make_stock(job, description="Assigned sheet")
    make_stock(stock_holding_job, description="Catalogue sheet", source="product_catalog")
    response = client.get(f"{URL}stock/", {"q": "sheet"})
    assert response.status_code == 200, response.content
    assert [row["id"] for row in response.json()["results"]] == [str(zero.id)]
    assert response.json()["count"] == 1


def test_posted_evidence_refuses_bulk_updates(client: Client, stock_holding_job: Job) -> None:
    stock = make_stock(stock_holding_job, quantity="0")
    count_id = start_count(client, stock)
    version = save_count(client, count_id, stock, "1")
    response = client.post(
        f"{URL}{count_id}/post/", {"version": version}, content_type="application/json"
    )
    assert response.status_code == 200, response.content
    movement = StockMovement.objects.get(stock=stock, kind="stocktake")
    with pytest.raises(DatabaseError), transaction.atomic():
        StockMovement.objects.filter(pk=movement.id).update(quantity_change=2)
    with pytest.raises(DatabaseError), transaction.atomic():
        Stocktake.objects.filter(pk=count_id).update(version=99)
    with pytest.raises(DatabaseError), transaction.atomic():
        Stocktake.objects.get(pk=count_id).lines.update(counted_quantity=2)
    assert movement.cost_line_id is not None
    with pytest.raises(DatabaseError), transaction.atomic():
        CostLine.objects.filter(pk=movement.cost_line_id).update(quantity=-2)
