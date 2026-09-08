"""Inbound Xero saves wait for real receipt transactions and preserve their evidence."""

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Staff
from apps.company.tests.factories import make_company
from apps.core.tests.concurrency import await_database_lock, start_database_task
from apps.job.models import Job
from apps.purchasing.etag import purchase_order_etag
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLine, StockMovement
from apps.purchasing.services.delivery_receipt_service import (
    ReceiptAllocationRequest,
    ReceiptLineRequest,
    process_delivery_receipt,
)
from apps.xero.transforms import transform_purchase_order

pytestmark = pytest.mark.committed_db


@pytest.mark.parametrize("received", [Decimal("1"), Decimal("2")])
def test_sync_waits_for_receipt_and_preserves_its_committed_status(
    office_staff: Staff, stock_holding_job: Job, received: Decimal
) -> None:
    supplier = make_company("Concurrency supplier", xero_contact_id=str(uuid4()))
    po = PurchaseOrder.objects.create(
        supplier=supplier,
        po_number=f"TEST-{uuid4()}",
        xero_id=uuid4(),
        status="submitted",
        xero_agreed_at=timezone.now(),
    )
    line = PurchaseOrderLine.objects.create(
        purchase_order=po,
        description="Received bar",
        quantity=2,
        unit_cost=10,
    )
    incoming = SimpleNamespace(
        contact=SimpleNamespace(contact_id=supplier.xero_contact_id, name=supplier.name),
        purchase_order_number=po.po_number,
        date="2026-05-05",
        status="VOIDED",
        updated_date_utc=timezone.now(),
        delivery_date=None,
        line_items=[],
    )

    def sync() -> str:
        result, _status = transform_purchase_order(incoming, str(po.xero_id))
        return result.status

    with (
        patch("apps.xero.transforms.queue_purchase_order_push"),
        ThreadPoolExecutor(max_workers=1) as pool,
    ):
        with transaction.atomic():
            process_delivery_receipt(
                po.id,
                {
                    str(line.id): ReceiptLineRequest(
                        total_received=received,
                        allocations=[
                            ReceiptAllocationRequest(
                                job_id=stock_holding_job.id,
                                quantity=received,
                                retail_rate=None,
                                metadata={},
                            )
                        ],
                    )
                },
                office_staff,
                if_match=purchase_order_etag(po),
            )
            pending, backend_pid = start_database_task(pool, sync)
            await_database_lock(pending, backend_pid)
        expected = "partially_received" if received == 1 else "fully_received"
        assert pending.result(timeout=10) == expected
    po.refresh_from_db()
    line.refresh_from_db()
    assert po.status == expected
    assert line.received_quantity == received
    receipt = StockMovement.objects.get(stock__source_purchase_order_line=line, kind="receipt")
    assert receipt.quantity_change == received
