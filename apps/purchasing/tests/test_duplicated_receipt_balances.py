"""A balance counted twice is emptied before the cutover opens the ledger on it."""

from decimal import Decimal
from importlib import import_module

import pytest
from django.db import DatabaseError, connection, transaction
from django.utils import timezone

from apps.job.models import Job
from apps.job.models.costing import CostLine
from apps.purchasing.models import Stock
from apps.purchasing.services.stock_movement_service import inventory_audit_findings
from apps.purchasing.tests.factories import make_po_line, make_purchase_order, make_stock

pytestmark = pytest.mark.django_db
RECONCILE = import_module("apps.purchasing.migrations.0007_reconcile_duplicated_receipt_balances")
OPENINGS = import_module("apps.purchasing.migrations.0011_backfill_job_openings")
BACKFILL = import_module("apps.purchasing.migrations.0015_backfill_legacy_receipt_evidence")
AUDIT = "Supplier receipt totals"


def reconcile() -> None:
    """Execute the forward data migration against historical fixture rows."""
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(RECONCILE.RECONCILE_SQL)


def run_cutover() -> None:
    """Book the openings and the lost receipt evidence, as a deploy's migrate run does."""
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(OPENINGS.STOCK_PROVENANCE_REPAIR_SQL)
        cursor.execute(OPENINGS.PREFLIGHT_SQL)
        cursor.execute(OPENINGS.BACKFILL_SQL)
        cursor.execute(BACKFILL.BACKFILL_SQL)


def duplicated_line(job: Job, stock_holding_job: Job, *, held: str) -> Stock:
    """Eleven sheets received, six charged out, 3.66 drawn, and ``held`` still on the shelf.

    Only 1.34 of those eleven remain unaccounted for, so any larger held balance is the
    same material recorded against two identities.
    """
    line = make_po_line(
        make_purchase_order(), quantity="11", unit_cost="379.50", received_quantity="11"
    )
    stock = make_stock(
        stock_holding_job,
        quantity=held,
        unit_cost="379.50",
        source="purchase_order",
        source_purchase_order_line=line,
    )
    booked_cost(job, "3.66", ext_refs={"stock_id": str(stock.id)})
    booked_cost(
        job,
        "6",
        ext_refs={
            "purchase_order_id": str(line.purchase_order_id),
            "purchase_order_line_id": str(line.id),
        },
    )
    return stock


def booked_cost(job: Job, quantity: str, *, ext_refs: dict[str, str]) -> CostLine:
    """A pre-cutover material charge, without a reconstructed receipt or issue."""
    return CostLine.objects.create(
        cost_set=job.cost_sets.get(kind="actual"),
        kind="material",
        desc="Stainless sheet",
        quantity=Decimal(quantity),
        unit_cost=Decimal("379.50"),
        unit_rev=Decimal("455.40"),
        accounting_date=timezone.localdate(),
        approved=True,
        ext_refs=ext_refs,
    )


def test_the_duplicated_balance_is_emptied_and_the_cutover_then_balances(
    job: Job, stock_holding_job: Job
) -> None:
    """The correction is what lets the deploy finish, so it is proved through the cutover."""
    stock = duplicated_line(job, stock_holding_job, held="6.29")

    reconcile()
    run_cutover()

    stock.refresh_from_db()
    assert stock.quantity == Decimal("1.34")
    assert AUDIT not in inventory_audit_findings()


def test_the_cutover_refuses_a_duplicated_balance_nobody_corrected(
    job: Job, stock_holding_job: Job
) -> None:
    """Without the correction the deploy stops inside migrate, which is what this fixes."""
    duplicated_line(job, stock_holding_job, held="6.29")

    with pytest.raises(DatabaseError, match="more receipt evidence than received quantity"):
        run_cutover()


def test_an_order_line_whose_evidence_already_balances_is_untouched(
    job: Job, stock_holding_job: Job
) -> None:
    """Reconciling must not move a balance that the order line's receipts already explain."""
    stock = duplicated_line(job, stock_holding_job, held="1.34")

    reconcile()

    stock.refresh_from_db()
    assert stock.quantity == Decimal("1.34")


def test_an_order_line_missing_evidence_is_left_for_the_backfill(
    job: Job, stock_holding_job: Job
) -> None:
    """A gap is booked as lost receipt evidence by 0015; emptying stock would deepen it."""
    stock = duplicated_line(job, stock_holding_job, held="0.5")

    reconcile()

    stock.refresh_from_db()
    assert stock.quantity == Decimal("0.5")


def test_reconciling_refuses_more_duplicated_lines_than_the_ceiling(
    job: Job, stock_holding_job: Job
) -> None:
    """Above a handful the duplication is a live writer, and emptying stock would hide it."""
    for _ in range(RECONCILE.DUPLICATED_BALANCE_LIMIT + 1):
        duplicated_line(job, stock_holding_job, held="6.29")

    with pytest.raises(DatabaseError, match="above the ceiling"):
        reconcile()


def test_reconciling_refuses_a_surplus_spread_across_two_identities(
    job: Job, stock_holding_job: Job
) -> None:
    """Which identity was superseded is then a judgement, and a migration may not make it."""
    duplicate = duplicated_line(job, stock_holding_job, held="6.29")
    make_stock(
        stock_holding_job,
        quantity="2",
        unit_cost="379.50",
        source="purchase_order",
        source_purchase_order_line=duplicate.source_purchase_order_line,
    )

    with pytest.raises(DatabaseError, match="not carried by exactly one identity"):
        reconcile()


def test_reconciling_refuses_a_surplus_larger_than_the_balance_held(
    job: Job, stock_holding_job: Job
) -> None:
    """A surplus the identity cannot cover is some other defect, not a duplicated balance."""
    line = make_po_line(
        make_purchase_order(), quantity="1", unit_cost="379.50", received_quantity="1"
    )
    stock = make_stock(
        stock_holding_job,
        quantity="1",
        unit_cost="379.50",
        source="purchase_order",
        source_purchase_order_line=line,
    )
    booked_cost(job, "3", ext_refs={"stock_id": str(stock.id)})

    with pytest.raises(DatabaseError, match="exceeds the balance held"):
        reconcile()
