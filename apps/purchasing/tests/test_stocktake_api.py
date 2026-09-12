"""Physical observations must reconcile inventory without erasing its history."""

from decimal import Decimal
from uuid import uuid4

import pytest
from django.db import DatabaseError, transaction
from django.test import Client

from apps.accounts.models import Staff
from apps.accounts.tests.helpers import authenticate
from apps.core.errors import InvalidInputError
from apps.job.models import Job
from apps.purchasing.models import (
    Stock,
    StockMovement,
    StockMovementKind,
    Stocktake,
    StocktakeConfiguration,
)
from apps.purchasing.services.stock_movement_service import (
    MovementContext,
    inventory_difference,
    move_stock,
)
from apps.purchasing.services.stock_service import consume_stock
from apps.purchasing.tests.factories import make_stock

pytestmark = pytest.mark.django_db
URL = "/api/purchasing/stocktakes/"


@pytest.mark.parametrize("suffix", ["", "setup/"])
def test_anonymous_stocktake_reads_and_writes_are_refused(client: Client, suffix: str) -> None:
    assert client.get(f"{URL}{suffix}").status_code == 401
    assert client.post(f"{URL}{suffix}", {}, content_type="application/json").status_code == 401
    assert not Stocktake.objects.exists()
    assert not StocktakeConfiguration.objects.exists()


def test_workshop_staff_can_use_the_shared_setup_and_create_a_count(
    client: Client, workshop_staff: Staff
) -> None:
    authenticate(client, workshop_staff)
    setup = client.post(f"{URL}setup/")
    assert setup.status_code == 200, setup.content
    created = client.post(URL, {}, content_type="application/json")
    assert created.status_code == 200, created.content
    assert created.json()["adjustment_job_id"] == setup.json()["adjustment_job_id"]


@pytest.mark.parametrize(
    "kind",
    [StockMovementKind.OPENING, StockMovementKind.JOB_OPENING, StockMovementKind.RECEIPT_OPENING],
)
def test_live_writer_refuses_cutover_observations(
    stock_holding_job: Job, kind: StockMovementKind
) -> None:
    stock = make_stock(stock_holding_job, quantity="0")
    with pytest.raises(InvalidInputError, match="cutover migration"):
        move_stock(stock, Decimal("1"), MovementContext(kind=kind, reason="Invalid opening"))
    stock.refresh_from_db()
    assert stock.quantity == 0
    assert stock.inventory_version == 0
    assert not stock.movements.exists()


def start_count(api: Client, stock: Stock) -> str:
    response = api.post(f"{URL}setup/")
    assert response.status_code == 200, response.content
    response = api.post(URL, {"stock_id": str(stock.id)}, content_type="application/json")
    assert response.status_code == 200, response.content
    return str(response.json()["id"])


def save_count(api: Client, count_id: str, stock: Stock, counted: str | None) -> str:
    detail = api.get(f"{URL}{count_id}/")
    body = detail.json()
    line = body["lines"][0]
    response = api.put(
        f"{URL}{count_id}/",
        {
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
        headers={"If-Match": detail.headers["ETag"]},
    )
    assert response.status_code == 200, response.content
    return response.headers["ETag"]


@pytest.mark.parametrize(
    ("recorded", "counted"), [("0", "1"), ("1", "0"), ("-1", "0"), ("2", "0.125"), ("1", "1")]
)
def test_count_balances_workshop_and_adjustment_job(
    api: Client,
    stock_holding_job: Job,
    recorded: str,
    counted: str,
) -> None:
    stock = make_stock(stock_holding_job, quantity=recorded, unit_cost="80")
    StockMovement.objects.create(
        stock=stock,
        kind=StockMovementKind.OPENING,
        quantity_change=Decimal(recorded),
        quantity_before=Decimal("0"),
        quantity_after=Decimal(recorded),
        unit_cost=Decimal("80"),
        reason="Cutover opening",
    )
    count_id = start_count(api, stock)
    version = save_count(api, count_id, stock, counted)
    response = api.post(f"{URL}{count_id}/post/", headers={"If-Match": version})
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
    retry = api.post(f"{URL}{count_id}/post/", headers={"If-Match": version})
    assert retry.status_code == 200, retry.content
    stock.refresh_from_db()
    assert stock.quantity == Decimal(counted)


def test_blank_count_does_not_write_stock(api: Client, stock_holding_job: Job) -> None:
    stock = make_stock(stock_holding_job)
    count_id = start_count(api, stock)
    version = save_count(api, count_id, stock, None)
    response = api.post(f"{URL}{count_id}/post/", headers={"If-Match": version})
    assert response.status_code == 400
    stock.refresh_from_db()
    assert stock.quantity == 10
    assert not stock.movements.exists()


def test_intervening_issue_requires_recount(
    api: Client,
    stock_holding_job: Job,
    job: Job,
    office_staff: Staff,
) -> None:
    stock = make_stock(stock_holding_job)
    count_id = start_count(api, stock)
    version = save_count(api, count_id, stock, "8")
    consume_stock(item=stock, job=job, qty=Decimal("2"), user=office_staff)
    response = api.post(f"{URL}{count_id}/post/", headers={"If-Match": version})
    assert response.status_code == 409
    assert "recount" in response.json()["detail"]
    assert Stocktake.objects.get(pk=count_id).posted_at is None
    assert not StockMovement.objects.filter(kind="stocktake").exists()


def test_new_material_requires_cost_and_is_created_only_on_post(
    api: Client,
    stock_holding_job: Job,
) -> None:
    stock = make_stock(stock_holding_job)
    count_id = start_count(api, stock)
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
    response = api.put(
        f"{URL}{count_id}/",
        {"lines": [line]},
        content_type="application/json",
        headers={"If-Match": api.get(f"{URL}{count_id}/").headers["ETag"]},
    )
    assert response.status_code == 422
    line["unit_cost"] = 80
    response = api.put(
        f"{URL}{count_id}/",
        {"lines": [line]},
        content_type="application/json",
        headers={"If-Match": api.get(f"{URL}{count_id}/").headers["ETag"]},
    )
    assert response.status_code == 200, response.content
    assert not Stock.objects.filter(description=line["description"]).exists()
    response = api.post(
        f"{URL}{count_id}/post/",
        headers={"If-Match": api.get(f"{URL}{count_id}/").headers["ETag"]},
    )
    assert response.status_code == 200, response.content
    found = Stock.objects.get(description=line["description"])
    assert found.quantity == 1
    assert found.job_id == stock_holding_job.id
    assert inventory_difference(found) == 0


def test_setup_is_explicit_and_idempotent(api: Client) -> None:
    assert api.get(f"{URL}setup/").json()["adjustment_job_id"] is None
    assert not StocktakeConfiguration.objects.exists()
    first = api.post(f"{URL}setup/")
    assert first.status_code == 200, first.content
    assert api.post(f"{URL}setup/").json() == first.json()
    assert StocktakeConfiguration.objects.count() == 1
    assert StocktakeConfiguration.objects.get().adjustment_job.shop_job


def test_correction_retains_original_posting(api: Client, stock_holding_job: Job) -> None:
    stock = make_stock(stock_holding_job, quantity="0")
    original = start_count(api, stock)
    version = save_count(api, original, stock, "1")
    assert api.post(f"{URL}{original}/post/", headers={"If-Match": version}).status_code == 200
    response = api.post(
        f"{URL}{original}/correct/",
        headers={"If-Match": api.get(f"{URL}{original}/").headers["ETag"]},
    )
    assert response.status_code == 200, response.content
    correction = response.json()
    assert correction["corrects_id"] == original
    stock.refresh_from_db()
    version = save_count(api, correction["id"], stock, "0")
    assert (
        api.post(f"{URL}{correction['id']}/post/", headers={"If-Match": version}).status_code == 200
    )
    stock.refresh_from_db()
    assert stock.quantity == 0
    assert StockMovement.objects.filter(stock=stock, kind="stocktake").count() == 2
    assert (
        api.put(
            f"{URL}{original}/",
            {"lines": []},
            content_type="application/json",
            headers={"If-Match": api.get(f"{URL}{original}/").headers["ETag"]},
        ).status_code
        == 400
    )


def test_failed_post_rolls_back_every_line(api: Client, stock_holding_job: Job) -> None:
    stock = make_stock(stock_holding_job, quantity="0")
    count_id = start_count(api, stock)
    body = api.get(f"{URL}{count_id}/").json()
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
    saved = api.put(
        f"{URL}{count_id}/",
        {"lines": [first, second]},
        headers={"If-Match": api.get(f"{URL}{count_id}/").headers["ETag"]},
        content_type="application/json",
    )
    assert saved.status_code == 200, saved.content
    result = api.post(
        f"{URL}{count_id}/post/",
        headers={"If-Match": api.get(f"{URL}{count_id}/").headers["ETag"]},
    )
    assert result.status_code == 400
    stock.refresh_from_db()
    assert stock.quantity == 0
    assert not StockMovement.objects.filter(kind="stocktake").exists()
    assert not Stock.objects.filter(description="Missing reason").exists()


def test_quantity_edits_and_retirement_cannot_hide_stock(
    api: Client, stock_holding_job: Job
) -> None:
    stock = make_stock(stock_holding_job, quantity="2")
    path = f"/api/purchasing/stock/{stock.id}/"
    assert api.patch(path, {"quantity": 0}, content_type="application/json").status_code == 422
    assert api.delete(path).status_code == 400
    stock.refresh_from_db()
    assert stock.quantity == 2
    assert stock.is_active


def test_return_issue_credits_job_without_erasing_original(
    api: Client,
    stock_holding_job: Job,
    job: Job,
    office_staff: Staff,
) -> None:
    stock = make_stock(stock_holding_job, quantity="0")
    line = consume_stock(item=stock, job=job, qty=Decimal("1"), user=office_staff)
    movement = StockMovement.objects.get(cost_line=line)
    endpoint = f"/api/purchasing/stock-movements/{movement.id}/return/"
    result = api.post(endpoint)
    assert result.status_code == 200, result.content
    assert api.post(endpoint).json()["id"] == result.json()["id"]
    stock.refresh_from_db()
    assert stock.quantity == 0
    line.refresh_from_db()
    assert line.quantity == 1
    credit = StockMovement.objects.get(reverses=movement).cost_line
    assert credit is not None
    assert credit.quantity == -1
    assert credit.unit_cost == line.unit_cost


def test_count_picker_includes_active_zero_workshop_material_only(
    api: Client,
    stock_holding_job: Job,
    job: Job,
) -> None:
    zero = make_stock(stock_holding_job, description="Countable sheet", quantity="0")
    make_stock(stock_holding_job, description="Retired sheet", quantity="0", is_active=False)
    make_stock(job, description="Assigned sheet")
    make_stock(stock_holding_job, description="Catalogue sheet", source="product_catalog")
    response = api.get("/api/purchasing/stock/search/", {"q": "sheet", "countable": "true"})
    assert response.status_code == 200, response.content
    assert [row["id"] for row in response.json()["results"]] == [str(zero.id)]
    assert response.json()["count"] == 1


def test_posted_evidence_survives_every_write_the_api_offers(
    api: Client, stock_holding_job: Job
) -> None:
    """Posted evidence is immutable because no writer changes it, not because a trigger blocks one.

    ADR 0058: the property is proved by driving every mutating route the posted count, its
    lines and its cost line expose, then reading the evidence back unchanged.
    """
    stock = make_stock(stock_holding_job, quantity="0")
    count_id = start_count(api, stock)
    version = save_count(api, count_id, stock, "1")
    assert api.post(f"{URL}{count_id}/post/", headers={"If-Match": version}).status_code == 200
    movement = StockMovement.objects.get(stock=stock, kind="stocktake")
    line = Stocktake.objects.get(pk=count_id).lines.get()
    before = (movement.quantity_change, movement.unit_cost, line.counted_quantity)
    cost_line = movement.cost_line
    assert cost_line is not None, "posting a count books a cost line against the movement"
    etag = api.get(f"{URL}{count_id}/").headers["ETag"]

    assert (
        api.put(
            f"{URL}{count_id}/",
            {"lines": []},
            content_type="application/json",
            headers={"If-Match": etag},
        ).status_code
        == 400
    )
    assert (
        api.patch(
            f"/api/job/cost_lines/{cost_line.id}/",
            {"quantity": "-2", "managed_by": None},
            content_type="application/json",
        ).status_code
        == 400
    )
    assert api.delete(f"/api/job/cost_lines/{cost_line.id}/delete/").status_code == 400

    movement.refresh_from_db()
    line.refresh_from_db()
    cost_line.refresh_from_db()
    assert (movement.quantity_change, movement.unit_cost, line.counted_quantity) == before
    assert cost_line.managed_by == "stocktake"
    assert StockMovement.objects.filter(stock=stock, kind="stocktake").count() == 1


@pytest.mark.parametrize("action", ["save", "post", "correct"])
def test_stocktake_mutations_require_the_observed_etag(
    api: Client, stock_holding_job: Job, action: str
) -> None:
    """An absent or obsolete draft precondition cannot overwrite or post another user's count."""
    stock = make_stock(stock_holding_job)
    count_id = start_count(api, stock)
    stale = api.get(f"{URL}{count_id}/").headers["ETag"]
    current = save_count(api, count_id, stock, "8")
    assert current != stale
    if action == "correct":
        assert api.post(f"{URL}{count_id}/post/", headers={"If-Match": current}).status_code == 200
    for headers, expected in [({}, 428), ({"If-Match": stale}, 412)]:
        if action == "save":
            response = api.put(
                f"{URL}{count_id}/", {"lines": []}, content_type="application/json", headers=headers
            )
        else:
            response = api.post(f"{URL}{count_id}/{action}/", headers=headers)
        assert response.status_code == expected, response.content
    count = Stocktake.objects.get(pk=count_id)
    assert count.lines.count() == 1
    assert count.lines.get().counted_quantity == Decimal("8")
    assert Stocktake.objects.count() == 1


def test_stock_observation_refresh_includes_unsaved_selected_items(
    api: Client, stock_holding_job: Job, job: Job, office_staff: Staff
) -> None:
    """A stock change must be visible even before a selected row has been saved to a draft."""
    selected = make_stock(stock_holding_job, quantity="10")
    make_stock(stock_holding_job, quantity="99")
    consume_stock(item=selected, job=job, qty=Decimal("2"), user=office_staff)
    response = api.get(
        "/api/purchasing/stock/search/?countable=true", {"stock_ids": [str(selected.id)]}
    )
    assert response.status_code == 200, response.content
    assert response.json()["count"] == 1
    row = response.json()["results"][0]
    assert row["id"] == str(selected.id)
    assert Decimal(row["quantity"]) == 8
    assert row["inventory_version"] == 1


@pytest.mark.parametrize("replace_id", [False, True])
def test_count_can_swap_stock_or_replace_a_row_in_one_save(
    api: Client, stock_holding_job: Job, replace_id: bool
) -> None:
    first = make_stock(stock_holding_job, quantity="2")
    second = make_stock(stock_holding_job, quantity="2")
    count_id = start_count(api, first)
    detail = api.get(f"{URL}{count_id}/")
    first_id, second_id = detail.json()["lines"][0]["id"], str(uuid4())
    rows = [
        {
            "id": row_id,
            "stock_id": str(stock.id),
            "description": stock.description,
            "location": None,
            "expected_quantity": "2",
            "expected_version": 0,
            "unit_cost": str(stock.unit_cost),
            "counted_quantity": "2",
            "reason": None,
        }
        for row_id, stock in [(first_id, first), (second_id, second)]
    ]
    saved = api.put(
        f"{URL}{count_id}/",
        {"lines": rows},
        content_type="application/json",
        headers={"If-Match": detail.headers["ETag"]},
    )
    assert saved.status_code == 200, saved.content
    if replace_id:
        rows[0]["id"] = str(uuid4())
    else:
        rows[0]["stock_id"], rows[1]["stock_id"] = rows[1]["stock_id"], rows[0]["stock_id"]
    saved = api.put(
        f"{URL}{count_id}/",
        {"lines": rows},
        content_type="application/json",
        headers={"If-Match": saved.headers["ETag"]},
    )
    assert saved.status_code == 200, saved.content
    assert {line["id"]: line["stock_id"] for line in saved.json()["lines"]} == {
        row["id"]: row["stock_id"] for row in rows
    }


@pytest.mark.parametrize("field", ["location", "reason"])
def test_count_rejects_blank_nullable_text_at_the_database(
    api: Client, stock_holding_job: Job, field: str
) -> None:
    count_id = start_count(api, make_stock(stock_holding_job))
    count = Stocktake.objects.get(pk=count_id)
    with pytest.raises(DatabaseError), transaction.atomic():
        count.lines.update(**{field: ""})


def test_setup_configuration_cannot_create_a_second_key(api: Client, job: Job) -> None:
    assert api.post(f"{URL}setup/").status_code == 200
    with pytest.raises(DatabaseError), transaction.atomic():
        StocktakeConfiguration.objects.bulk_create(
            [StocktakeConfiguration(id=2, adjustment_job=job)]
        )
    assert list(StocktakeConfiguration.objects.values_list("id", flat=True)) == [1]
