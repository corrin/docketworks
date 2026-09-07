"""Cutover preserves booked costs and permits audited returns at historical prices."""

from decimal import Decimal
from importlib import import_module

import pytest
from django.db import DatabaseError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import Client
from django.utils import timezone

from apps.accounts.models import Staff
from apps.job.models import Job
from apps.job.models.costing import CostLine
from apps.purchasing.models import Stock, StockMovement
from apps.purchasing.services.stock_movement_service import inventory_difference
from apps.purchasing.tests.conftest import make_po_line, make_purchase_order, make_stock

pytestmark = pytest.mark.django_db


def apply_openings(name: str = "0011_backfill_job_openings") -> None:
    """Execute the forward data migration against historical fixture rows."""
    migration = import_module(f"apps.purchasing.migrations.{name}")
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(migration.PREFLIGHT_SQL)
        cursor.execute(migration.BACKFILL_SQL)


def historical_cost(job: Job, stock: Stock, *, approved: bool = True) -> CostLine:
    """A pre-cutover booked position, without a reconstructed receipt or issue."""
    return CostLine.objects.create(
        cost_set=job.cost_sets.get(kind="actual"),
        kind="material",
        desc="Historical sheet",
        quantity=Decimal("2"),
        unit_cost=Decimal("15"),
        unit_rev=Decimal("22"),
        accounting_date=timezone.localdate(),
        approved=approved,
        ext_refs={"stock_id": str(stock.id)},
    )


def test_migration_preserves_balances_costs_and_original_identity(
    job: Job, stock_holding_job: Job
) -> None:
    """Opening a job position must not charge the job or consume its stock a second time."""
    stock = make_stock(stock_holding_job, quantity="-3", unit_cost="80", source="product_catalog")
    line = historical_cost(job, stock)
    difference = inventory_difference(stock)
    apply_openings()
    apply_openings()
    stock.refresh_from_db()
    line.refresh_from_db()
    opening = StockMovement.objects.get(cost_line=line)
    assert (stock.quantity, stock.unit_cost, inventory_difference(stock)) == (
        Decimal("-3"),
        Decimal("80"),
        difference,
    )
    assert (line.quantity, line.unit_cost, line.unit_rev, line.managed_by) == (
        Decimal("2"),
        Decimal("15"),
        Decimal("22"),
        "stock",
    )
    assert (opening.kind, opening.quantity_change, opening.unit_cost) == (
        "job_opening",
        Decimal("0"),
        Decimal("15"),
    )
    assert opening.actor_id is None
    with pytest.raises(DatabaseError), transaction.atomic():
        CostLine.objects.filter(pk=line.pk).update(quantity=5)


def test_migrated_job_position_returns_once_at_original_prices(
    client: Client, job: Job, stock_holding_job: Job, office_staff: Staff
) -> None:
    """Returning migrated material preserves its charge and credits its original price once."""
    stock = make_stock(stock_holding_job, quantity="3", unit_cost="80", is_active=False)
    line = historical_cost(job, stock)
    apply_openings()
    opening = StockMovement.objects.get(cost_line=line)
    endpoint = f"/api/purchasing/stock-movements/{opening.id}/return/"
    response = client.post(endpoint)
    assert response.status_code == 200, response.content
    assert client.post(endpoint).json()["id"] == response.json()["id"]
    returned = StockMovement.objects.get(reverses=opening)
    credit = returned.cost_line
    assert credit is not None
    assert (credit.quantity, credit.unit_cost, credit.unit_rev) == (
        Decimal("-2"),
        Decimal("15"),
        Decimal("22"),
    )
    assert (returned.quantity_change, returned.unit_cost, returned.actor_id) == (
        Decimal("2"),
        Decimal("15"),
        office_staff.id,
    )
    stock.refresh_from_db()
    line.refresh_from_db()
    assert stock.is_active
    assert (stock.quantity, stock.unit_cost, line.quantity) == (
        Decimal("5"),
        Decimal("80"),
        Decimal("2"),
    )
    assert (
        client.patch(
            f"/api/job/cost_lines/{line.id}/", {"quantity": 8}, content_type="application/json"
        ).status_code
        == 400
    )
    assert client.delete(f"/api/job/cost_lines/{line.id}/delete/").status_code == 400


def test_unapproved_position_is_not_migrated(job: Job, stock_holding_job: Job) -> None:
    """A stock selection awaiting approval is not evidence of an issue."""
    stock = make_stock(stock_holding_job)
    line = historical_cost(job, stock, approved=False)
    apply_openings()
    line.refresh_from_db()
    assert line.managed_by is None
    assert not StockMovement.objects.filter(cost_line=line).exists()


def test_invalid_position_aborts_all_openings(job: Job, stock_holding_job: Job) -> None:
    """One ambiguous position prevents a partially migrated inventory."""
    stock = make_stock(stock_holding_job)
    valid = historical_cost(job, stock)
    invalid = historical_cost(job, stock)
    invalid.quantity = 0
    invalid.save()
    with pytest.raises(DatabaseError, match="Job opening preflight failed"):
        apply_openings()
    valid.refresh_from_db()
    assert valid.managed_by is None
    assert not StockMovement.objects.filter(cost_line=valid).exists()


def test_receipt_opening_preserves_totals_and_uses_the_same_reversal(
    client: Client, job: Job, stock_holding_job: Job, office_staff: Staff
) -> None:
    """A migrated receipt returns through the normal command, preserving its original job charge."""
    po = make_purchase_order(status="fully_received")
    po_line = make_po_line(po, quantity="2", received_quantity="2", unit_cost="80")
    original = CostLine.objects.create(
        cost_set=job.cost_sets.get(kind="actual"),
        kind="material",
        desc="Old receipt",
        quantity=Decimal("2"),
        unit_cost=Decimal("15"),
        unit_rev=Decimal("22"),
        accounting_date=timezone.localdate(),
        approved=True,
        ext_refs={"purchase_order_id": str(po.id), "purchase_order_line_id": str(po_line.id)},
    )
    apply_openings()
    apply_openings()
    opening = StockMovement.objects.get(cost_line=original)
    stock = opening.stock
    assert stock.job_id == stock_holding_job.id
    assert stock.quantity == 0
    assert not stock.is_active
    assert inventory_difference(stock) == 0
    original.refresh_from_db()
    po_line.refresh_from_db()
    assert original.unit_cost == Decimal("15")
    assert po_line.received_quantity == Decimal("2")
    receipt = stock.movements.get(kind="receipt_opening")
    assert receipt.opening_quantity == Decimal("2")
    assert not client.get("/api/purchasing/stocktakes/stock/").json()["results"]
    detail = client.get(f"/api/purchasing/purchase-orders/{po.id}/")
    path = f"/api/purchasing/purchase-orders/{po.id}/lines/{po_line.id}/allocations/delete/"
    response = client.post(
        path,
        {"allocation_type": "job", "allocation_id": str(original.id)},
        content_type="application/json",
        headers={"If-Match": detail.headers["ETag"]},
    )
    assert response.status_code == 200, response.content
    stock.refresh_from_db()
    po_line.refresh_from_db()
    assert stock.quantity == 0
    assert po_line.received_quantity == 0
    returned = StockMovement.objects.get(reverses=opening)
    supplier_reversal = StockMovement.objects.get(reverses=receipt)
    assert returned.actor_id == office_staff.id
    assert supplier_reversal.actor_id == office_staff.id
    assert returned.cost_line is not None
    assert returned.cost_line.unit_cost == Decimal("15")
    assert CostLine.objects.filter(pk=original.id, quantity=2).exists()


def test_missing_receipt_provenance_aborts_without_freezing_costs(job: Job) -> None:
    """Missing original PO lines cannot be guessed into a new receipt identity."""
    po = make_purchase_order()
    original = CostLine.objects.create(
        cost_set=job.cost_sets.get(kind="actual"),
        kind="material",
        desc="Missing receipt line",
        quantity=Decimal("2"),
        unit_cost=Decimal("15"),
        unit_rev=Decimal("22"),
        accounting_date=timezone.localdate(),
        approved=True,
        ext_refs={"purchase_order_id": str(po.id)},
    )
    with pytest.raises(DatabaseError, match="Receipt opening preflight failed"):
        apply_openings()
    original.refresh_from_db()
    assert original.managed_by is None
    assert not StockMovement.objects.filter(cost_line=original).exists()


def test_receipt_preflight_prevents_partial_stock_job_migration(
    job: Job, stock_holding_job: Job
) -> None:
    """A bad receipt stops all job openings, including independently valid stock issues."""
    valid = historical_cost(job, make_stock(stock_holding_job))
    orphan = historical_cost(job, make_stock(stock_holding_job))
    orphan.ext_refs = {"purchase_order_id": str(make_purchase_order().id)}
    orphan.save()
    with pytest.raises(DatabaseError, match="Receipt opening preflight failed"):
        apply_openings()
    valid.refresh_from_db()
    assert valid.managed_by is None
    assert not StockMovement.objects.filter(cost_line=valid).exists()


def test_posted_return_does_not_fail_pending_receipt_preflight(
    job: Job, stock_holding_job: Job, office_staff: Staff
) -> None:
    stock = make_stock(stock_holding_job)
    original = historical_cost(job, stock)
    apply_openings()
    opening = StockMovement.objects.get(cost_line=original)
    credit = CostLine.objects.create(
        cost_set=original.cost_set,
        kind="material",
        desc="Posted supplier credit",
        accounting_date=timezone.localdate(),
        quantity=-original.quantity,
        unit_cost=original.unit_cost,
        unit_rev=original.unit_rev,
        approved=True,
        managed_by="stock",
        ext_refs={"purchase_order_id": str(make_purchase_order().id)},
    )
    StockMovement.objects.create(
        stock=stock,
        kind="return",
        quantity_change=2,
        quantity_before=stock.quantity,
        quantity_after=stock.quantity + 2,
        unit_cost=credit.unit_cost,
        counterpart_job=job,
        cost_line=credit,
        reverses=opening,
        actor=office_staff,
        reason="Historical return",
    )
    apply_openings()
    assert StockMovement.objects.filter(cost_line=credit).count() == 1


@pytest.mark.parametrize("description", [None, "   "])
def test_receipt_without_stock_description_refuses_before_any_backfill(
    job: Job, stock_holding_job: Job, description: str | None
) -> None:
    valid = historical_cost(job, make_stock(stock_holding_job))
    po = make_purchase_order()
    line = make_po_line(po)
    invalid = historical_cost(job, make_stock(stock_holding_job))
    invalid.desc = description
    invalid.ext_refs = {"purchase_order_id": str(po.id), "purchase_order_line_id": str(line.id)}
    invalid.save()
    with pytest.raises(DatabaseError, match="Receipt opening preflight failed"):
        apply_openings()
    valid.refresh_from_db()
    assert valid.managed_by is None
    assert not StockMovement.objects.filter(cost_line=valid).exists()


def test_receipt_cutover_executor_is_atomic_and_repeatable(
    job: Job, stock_holding_job: Job
) -> None:
    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
    executor = MigrationExecutor(connection)
    executor.migrate([("purchasing", "0010_job_position_openings")])
    original = historical_cost(job, make_stock(stock_holding_job))
    orphan = historical_cost(job, make_stock(stock_holding_job))
    orphan.ext_refs = {"purchase_order_id": str(make_purchase_order().id)}
    orphan.save()
    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
    with (
        pytest.raises(DatabaseError, match="Receipt opening preflight failed"),
        transaction.atomic(),
    ):
        MigrationExecutor(connection).migrate([("purchasing", "0011_backfill_job_openings")])
    original.refresh_from_db()
    assert original.managed_by is None
    assert not StockMovement.objects.filter(cost_line=original).exists()
    # GPT: the refused row is a test fixture, not a production repair policy.
    orphan.delete()
    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())
    first = StockMovement.objects.get(cost_line=original)
    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())
    assert StockMovement.objects.get(cost_line=original).id == first.id
