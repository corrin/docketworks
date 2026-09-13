"""Inventory waits for costing jobs before taking stock locks."""

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command
from django.db import transaction

from apps.accounts.models import Staff
from apps.company.models import Company
from apps.company.tests.job_fixtures import make_job, make_material_line
from apps.core.errors import ConflictError
from apps.core.etag import generate_revision_etag
from apps.core.tests.concurrency import await_database_lock, start_database_task
from apps.job.models import Job
from apps.purchasing.etag import purchase_order_etag
from apps.purchasing.models import Stock, Stocktake
from apps.purchasing.services.delivery_receipt_service import (
    ReceiptAllocationRequest,
    ReceiptLineRequest,
    process_delivery_receipt,
)
from apps.purchasing.services.stock_movement_service import reverse_issue
from apps.purchasing.services.stock_service import consume_stock
from apps.purchasing.services.stocktake_service import (
    configure_stocktake,
    create_stocktake,
    post_stocktake,
    save_stocktake,
)
from apps.purchasing.stocktake_schemas import StocktakeLineWrite, StocktakeSave
from apps.purchasing.tests.factories import make_po_line, make_purchase_order, receive_po_line

pytestmark = pytest.mark.committed_db


@pytest.mark.parametrize("returning", [False, True])
def test_inventory_waits_for_a_cost_save_before_locking_stock(
    office_staff: Staff, job: Job, stock_holding_job: Job, returning: bool
) -> None:
    po = make_purchase_order(status="submitted")
    line = make_po_line(po, quantity="4")
    receive_po_line(line, Decimal("4"), job, stock_holding_job, office_staff)
    stock = Stock.objects.get(source_purchase_order_line=line, quantity=2)
    original = None
    if returning:
        original = consume_stock(item=stock, job=job, qty=Decimal("1"), user=office_staff)

    def mutate_inventory() -> None:
        if original is None:
            consume_stock(item=stock, job=job, qty=Decimal("1"), user=office_staff)
        else:
            reverse_issue(original.stockmovement, office_staff, "Unused material")

    with ThreadPoolExecutor(max_workers=1) as pool:
        with transaction.atomic():
            make_material_line(job)
            pending, worker_pid = start_database_task(pool, mutate_inventory)
            await_database_lock(pending, worker_pid)
            # If inventory took stock first, this would fail while the worker
            # waits for the job held by the real CostLine.save above.
            Stock.objects.select_for_update(nowait=True).get(pk=stock.id)
        pending.result(timeout=10)
    stock.refresh_from_db()
    assert stock.quantity == (Decimal("2") if returning else Decimal("1"))
    output = StringIO()
    call_command("audit_inventory_openings", stdout=output)
    assert "ledger audit passed" in output.getvalue()


def test_count_waits_for_issue_and_refuses_the_changed_observation(
    office_staff: Staff, job: Job, stock_holding_job: Job
) -> None:
    """A posting must recheck stock after a concurrent issue releases its lock."""
    po = make_purchase_order(status="submitted")
    receipt_line = make_po_line(po, quantity="4")
    receive_po_line(receipt_line, Decimal("4"), job, stock_holding_job, office_staff)
    stock = Stock.objects.get(source_purchase_order_line=receipt_line, quantity=2)
    configure_stocktake(office_staff)
    count = create_stocktake(office_staff, stock.id)
    line = count.lines.get()
    count = save_stocktake(
        count.id,
        StocktakeSave(
            lines=[
                StocktakeLineWrite(
                    id=line.id,
                    stock_id=stock.id,
                    description=stock.description,
                    location=stock.location,
                    expected_version=stock.inventory_version,
                    expected_quantity=stock.quantity,
                    counted_quantity=Decimal("0"),
                    unit_cost=stock.unit_cost,
                    reason="Physical count",
                )
            ]
        ),
        if_match=generate_revision_etag("stocktake", count.id, count.version),
    )

    def post() -> Stocktake:
        return post_stocktake(
            count.id, generate_revision_etag("stocktake", count.id, count.version), office_staff
        )

    with ThreadPoolExecutor(max_workers=1) as pool:
        with transaction.atomic():
            consume_stock(item=stock, job=job, qty=Decimal("1"), user=office_staff)
            pending, worker_pid = start_database_task(pool, post)
            await_database_lock(pending, worker_pid)
        with pytest.raises(ConflictError):
            pending.result(timeout=10)
    stock.refresh_from_db()
    count.refresh_from_db()
    assert stock.quantity == 1
    assert count.posted_at is None
    assert not stock.movements.filter(kind="stocktake").exists()


@pytest.mark.usefixtures("stock_holding_job")
def test_receipt_locks_jobs_in_identity_order_despite_allocation_order(
    office_staff: Staff, job: Job, company: Company
) -> None:
    """Reversed allocation input must not acquire the second job before the first."""
    other = make_job(company, office_staff, name="Second receipt job")
    first, second = sorted((job, other), key=lambda target: target.id)
    po = make_purchase_order(status="submitted")
    line = make_po_line(po, quantity="2")

    def receive() -> object:
        return process_delivery_receipt(
            po.id,
            {
                str(line.id): ReceiptLineRequest(
                    total_received=Decimal("2"),
                    allocations=[
                        ReceiptAllocationRequest(
                            job_id=target.id, quantity=Decimal("1"), retail_rate=None, metadata={}
                        )
                        for target in (second, first)
                    ],
                )
            },
            office_staff,
            if_match=purchase_order_etag(po),
        )

    with ThreadPoolExecutor(max_workers=1) as pool:
        with transaction.atomic():
            make_material_line(first)
            pending, worker_pid = start_database_task(pool, receive)
            await_database_lock(pending, worker_pid)
            Job.objects.select_for_update(nowait=True).get(pk=second.id)
        pending.result(timeout=10)
    line.refresh_from_db()
    assert line.received_quantity == 2
    for target in (first, second):
        costs = target.latest_actual.cost_lines.filter(meta__po_number=po.po_number)
        assert sum(cost.quantity for cost in costs) == 1
