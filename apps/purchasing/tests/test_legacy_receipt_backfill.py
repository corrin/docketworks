"""Lost receipt evidence is booked as an opening, so one data model survives the cutover."""

from decimal import Decimal
from importlib import import_module

import pytest
from django.db import connection, transaction

from apps.job.models import Job
from apps.purchasing.models import Stock, StockMovement
from apps.purchasing.services.stock_movement_service import inventory_audit_findings
from apps.purchasing.tests.factories import make_po_line, make_purchase_order, make_stock

pytestmark = pytest.mark.django_db
AUDIT = "Supplier receipt totals"


def apply_backfill() -> None:
    """Execute the forward data migration against historical fixture rows."""
    migration = import_module("apps.purchasing.migrations.0015_backfill_legacy_receipt_evidence")
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(migration.BACKFILL_SQL)


@pytest.mark.usefixtures("stock_holding_job")
def test_gap_becomes_receipt_evidence_and_closes_the_audit() -> None:
    """A line whose receipts were lost is explained by an opening, not by a second data model.

    ADR 0059: the ledger already represents "received historically, no balance remains",
    so the gap is migrated into that shape rather than recorded as a permanent exception.
    """
    po = make_purchase_order()
    line = make_po_line(po, quantity="4", unit_cost="12", received_quantity="4")
    assert str(line.id) in inventory_audit_findings()[AUDIT]

    apply_backfill()

    movement = StockMovement.objects.get(stock__source_purchase_order_line=line)
    assert (movement.kind, movement.quantity_change, movement.opening_quantity) == (
        "receipt_opening",
        Decimal("0"),
        Decimal("4"),
    )
    assert AUDIT not in inventory_audit_findings()


def test_backfill_moves_no_stock_and_repeats_without_double_booking(
    stock_holding_job: Job,
) -> None:
    """Evidence of a past receipt must not become stock somebody could issue today."""
    po = make_purchase_order()
    make_po_line(po, quantity="4", unit_cost="12", received_quantity="4")
    held = make_stock(stock_holding_job, quantity="7")

    apply_backfill()
    apply_backfill()

    held.refresh_from_db()
    assert held.quantity == Decimal("7")
    assert StockMovement.objects.filter(kind="receipt_opening").count() == 1
    assert Stock.objects.filter(source="purchase_order").get().quantity == Decimal("0")
    assert AUDIT not in inventory_audit_findings()


@pytest.mark.usefixtures("stock_holding_job")
def test_a_receipt_recorded_after_the_backfill_is_still_audited() -> None:
    """Closing the historical gap must not excuse the line from every later discrepancy."""
    po = make_purchase_order()
    line = make_po_line(po, quantity="6", unit_cost="12", received_quantity="4")
    apply_backfill()
    assert AUDIT not in inventory_audit_findings()

    line.received_quantity = Decimal("6")
    line.save(update_fields=["received_quantity"])

    assert str(line.id) in inventory_audit_findings()[AUDIT]
