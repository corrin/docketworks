"""Reviewed orphan adjustments preserve booked amounts without fabricating receipt history."""

from decimal import Decimal
from uuid import uuid4

import pytest
from django.utils import timezone

from adhoc.inventory_cost_repair import (
    Disposition,
    RepairManifest,
    StockDisposition,
    repair,
)
from apps.accounts.models import Staff
from apps.company.tests.factories import make_company
from apps.company.tests.job_fixtures import make_job
from apps.job.models import Job
from apps.job.models.costing import CostLine
from apps.purchasing.models import StockMovement
from apps.purchasing.tests.factories import make_po_line, make_purchase_order, make_stock

pytestmark = pytest.mark.django_db


@pytest.fixture
def job(office_staff: Staff) -> Job:
    """A customer job whose original accounting periods must survive the repair."""
    return make_job(make_company("Repair fixture customer"), office_staff)


@pytest.mark.parametrize("unit_cost", [Decimal("12.90"), Decimal("0")])
def test_adjustment_reclassification_preserves_financial_history(
    job: Job, unit_cost: Decimal
) -> None:
    """Changing receipt classification must not add charges or move them between reporting dates."""
    po = make_purchase_order()
    dead = uuid4()
    cost = CostLine.objects.create(
        cost_set=job.cost_sets.get(kind="actual"),
        kind="material",
        desc="Unrecoverable receipt",
        quantity=2,
        unit_cost=unit_cost,
        unit_rev=Decimal("15.48"),
        accounting_date=timezone.localdate(),
        approved=True,
        ext_refs={"purchase_order_id": str(po.id), "purchase_order_line_id": str(dead)},
        meta={"source": "delivery_receipt", "retail_rate": 0.2},
    )
    plan = RepairManifest(
        rows=[
            Disposition(
                cost_id=cost.id,
                purchase_order_id=po.id,
                dead_line_id=dead,
                job_number=job.job_number,
                quantity=Decimal("2"),
                unit_cost=unit_cost,
                reason="Owner approved an adjustment after the source line could not be recovered.",
            )
        ]
    )
    before = (cost.cost_set_id, cost.quantity, cost.unit_cost, cost.unit_rev, cost.accounting_date)
    assert repair(plan, apply=False) == 1
    cost.refresh_from_db()
    assert cost.kind == "material"
    assert repair(plan, apply=True) == 1
    assert repair(plan, apply=True) == 0
    cost.refresh_from_db()
    assert cost.kind == "adjust"
    assert (
        cost.cost_set_id,
        cost.quantity,
        cost.unit_cost,
        cost.unit_rev,
        cost.accounting_date,
    ) == before
    assert str(dead) in cost.meta["comments"]
    assert cost.ext_refs == {}
    assert not StockMovement.objects.filter(cost_line=cost).exists()
    cost.cost_set.refresh_from_db()
    assert cost.cost_set.summary["cost"] == float(unit_cost * 2)
    assert cost.cost_set.summary["rev"] == 30.96


def test_relink_refuses_a_replacement_already_claimed_by_another_cost(job: Job) -> None:
    """A previously verified match is no longer safe once another receipt claims it."""
    po = make_purchase_order()
    replacement = make_po_line(po, job=job, quantity="1", received_quantity="1", unit_cost="10")
    dead = uuid4()
    original = CostLine.objects.create(
        cost_set=job.cost_sets.get(kind="actual"),
        kind="material",
        desc=replacement.description,
        quantity=1,
        unit_cost=10,
        unit_rev=12,
        accounting_date=timezone.localdate(),
        approved=True,
        ext_refs={"purchase_order_id": str(po.id), "purchase_order_line_id": str(dead)},
    )
    plan = RepairManifest(
        rows=[
            Disposition(
                cost_id=original.id,
                purchase_order_id=po.id,
                dead_line_id=dead,
                job_number=job.job_number,
                quantity=Decimal("1"),
                unit_cost=Decimal("10"),
                replacement_line_id=replacement.id,
                reason="Reviewed exact match",
            )
        ]
    )
    assert repair(plan, apply=False) == 1
    claimant = CostLine.objects.create(
        cost_set=original.cost_set,
        kind="material",
        desc=replacement.description,
        quantity=1,
        unit_cost=10,
        unit_rev=12,
        accounting_date=timezone.localdate(),
        ext_refs={"purchase_order_line_id": str(replacement.id)},
    )
    with pytest.raises(ValueError, match="no longer matches"):
        repair(plan, apply=True)
    original.refresh_from_db()
    assert original.ext_refs["purchase_order_line_id"] == str(dead)
    claimant.delete()
    assert repair(plan, apply=True) == 1
    original.refresh_from_db()
    assert original.ext_refs["purchase_order_line_id"] == str(replacement.id)
    assert original.kind == "material"


def test_absent_line_reference_can_be_documented_without_inventing_one(job: Job) -> None:
    """Older receipts sometimes retained only their PO identity."""
    po = make_purchase_order()
    cost = CostLine.objects.create(
        cost_set=job.cost_sets.get(kind="actual"),
        kind="material",
        desc="Old material",
        quantity=1,
        unit_cost=30,
        unit_rev=36,
        accounting_date=timezone.localdate(),
        approved=True,
        ext_refs={"purchase_order_id": str(po.id)},
    )
    manifest = RepairManifest(
        rows=[
            Disposition(
                cost_id=cost.id,
                purchase_order_id=po.id,
                dead_line_id=None,
                job_number=job.job_number,
                quantity=Decimal(1),
                unit_cost=Decimal(30),
                reason="Legacy source line is missing; original booked charge retained.",
            )
        ]
    )
    assert repair(manifest, apply=True) == 1
    assert repair(manifest, apply=True) == 0
    cost.refresh_from_db()
    assert cost.kind == "adjust"
    assert cost.meta["comments"].startswith("Legacy source line is missing")
    assert cost.total_cost == 30
    assert not StockMovement.objects.filter(cost_line=cost).exists()


def test_stock_source_repair_preserves_its_opening(stock_holding_job: Job) -> None:
    """Losing a receipt link does not justify deleting stock or replacing its opening."""
    stock = make_stock(stock_holding_job, quantity="4", unit_cost="20", source="purchase_order")
    opening = StockMovement.objects.create(
        stock=stock,
        kind="opening",
        quantity_before=0,
        quantity_after=4,
        quantity_change=4,
        unit_cost=20,
        reason="Original inventory cutover",
    )
    manifest = RepairManifest(
        stock_rows=[
            StockDisposition(
                stock_id=stock.id,
                description=stock.description,
                quantity=Decimal(4),
                unit_cost=Decimal(20),
                opening_id=opening.id,
                reason="Legacy receipt source missing; opening balance retained.",
            )
        ]
    )
    assert repair(manifest, apply=False) == 1
    assert repair(manifest, apply=True) == 1
    assert repair(manifest, apply=True) == 0
    stock.refresh_from_db()
    assert stock.source == "manual"
    assert stock.quantity == 4
    assert stock.unit_cost == 20
    assert stock.movements.get().id == opening.id
    assert "Legacy receipt source missing" in stock.description
