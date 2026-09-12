"""Recurring reconciliation reports ledger defects without repairing their evidence."""

from decimal import Decimal

import pytest
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.accounts.models import Staff
from apps.job.models import Job
from apps.job.models.costing import CostLine
from apps.purchasing.models import PurchaseOrderLine, Stock, StockMovement
from apps.purchasing.services.stock_movement_service import inventory_audit_findings
from apps.purchasing.tests.factories import (
    make_po_line,
    make_purchase_order,
    make_stock,
    receive_po_line,
)

pytestmark = pytest.mark.django_db


def test_audit_accepts_live_receipts_issues_and_reversals_without_writes(
    api: Client, office_staff: Staff, stock_holding_job: Job, job: Job
) -> None:
    po = make_purchase_order(status="submitted")
    line = make_po_line(po, quantity="4")
    receive_po_line(line, Decimal("4"), job, stock_holding_job, office_staff)
    assert inventory_audit_findings() == {}
    cost = job.cost_sets.get(kind="actual").cost_lines.get()
    detail = api.get(f"/api/purchasing/purchase-orders/{po.id}/")
    response = api.post(
        f"/api/purchasing/purchase-orders/{po.id}/lines/{line.id}/allocations/reverse/",
        {"allocation_type": "job", "allocation_id": str(cost.id)},
        content_type="application/json",
        headers={"If-Match": detail.headers["ETag"]},
    )
    assert response.status_code == 200, response.content
    with CaptureQueriesContext(connection) as queries:
        assert inventory_audit_findings() == {}
    assert all(query["sql"].lstrip().startswith(("SELECT", "WITH")) for query in queries)


def test_audit_reports_retired_stock_balance_drift_without_repair(stock_holding_job: Job) -> None:
    stock = make_stock(stock_holding_job, quantity="-3", is_active=False)
    findings = inventory_audit_findings()
    assert findings["Stock balances"] == [f"{stock.id}: recorded=-3.000, ledger=0"]
    stock.refresh_from_db()
    assert stock.quantity == -3
    assert not stock.movements.exists()


def test_audit_detects_a_broken_chain_even_when_the_total_matches(stock_holding_job: Job) -> None:
    stock = make_stock(stock_holding_job, quantity="3")
    StockMovement.objects.create(
        stock=stock,
        kind="receipt",
        quantity_change=2,
        quantity_before=0,
        quantity_after=2,
        unit_cost=stock.unit_cost,
        reason="First receipt",
    )
    broken = StockMovement.objects.create(
        stock=stock,
        kind="receipt",
        quantity_change=1,
        quantity_before=0,
        quantity_after=1,
        unit_cost=stock.unit_cost,
        reason="Incorrect preceding balance",
    )
    findings = inventory_audit_findings()
    assert "Stock balances" not in findings
    assert findings["Movement continuity"] == [str(broken.id)]


def test_audit_reports_supplier_totals_disagreeing_with_receipt_evidence(
    office_staff: Staff, stock_holding_job: Job, job: Job
) -> None:
    po = make_purchase_order(status="submitted")
    line = make_po_line(po, quantity="4")
    receive_po_line(line, Decimal("4"), job, stock_holding_job, office_staff)
    # Deliberately corrupt the projection; the real receipt evidence remains immutable.
    PurchaseOrderLine.objects.filter(pk=line.id).update(received_quantity=3)
    assert inventory_audit_findings()["Supplier receipt totals"] == [str(line.id)]
    assert Stock.objects.filter(source_purchase_order_line=line).count() == 2


def test_audit_compares_the_original_cost_price_with_its_opening(
    stock_holding_job: Job, job: Job
) -> None:
    stock = make_stock(stock_holding_job, quantity="0")
    cost = CostLine.objects.create(
        cost_set=job.cost_sets.get(kind="actual"),
        kind="material",
        desc="Booked sheet",
        quantity=1,
        unit_cost=20,
        unit_rev=25,
        managed_by="stock",
        accounting_date=timezone.localdate(),
    )
    opening = StockMovement.objects.create(
        stock=stock,
        kind="job_opening",
        quantity_change=0,
        quantity_before=0,
        quantity_after=0,
        unit_cost=99,
        counterpart_job=job,
        cost_line=cost,
        reason="Incorrect price observation",
    )
    assert inventory_audit_findings()["Job cost counterparts"] == [str(opening.id)]
    cost.refresh_from_db()
    assert cost.unit_cost == 20


def test_pending_receipt_totals_become_auditable_after_the_opening(stock_holding_job: Job) -> None:
    po = make_purchase_order(status="fully_received")
    line = make_po_line(po, quantity="2", received_quantity=Decimal("2"))
    stock = make_stock(
        stock_holding_job, quantity="2", source="purchase_order", source_purchase_order_line=line
    )
    StockMovement.objects.create(
        stock=stock,
        kind="opening",
        quantity_change=2,
        quantity_before=0,
        quantity_after=2,
        unit_cost=stock.unit_cost,
        reason="Physical cutover balance",
    )
    assert inventory_audit_findings() == {}
    StockMovement.objects.create(
        stock=stock,
        kind="receipt_opening",
        quantity_change=0,
        quantity_before=2,
        quantity_after=2,
        unit_cost=stock.unit_cost,
        opening_quantity=1,
        reason="Incomplete receipt observation",
    )
    assert inventory_audit_findings()["Supplier receipt totals"] == [str(line.id)]
