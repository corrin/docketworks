"""Purchasing test data and receipt actions; fixture wiring lives in conftest."""

from decimal import Decimal

from apps.accounts.models import Staff
from apps.company.models import Company
from apps.job.models import Job
from apps.purchasing.etag import purchase_order_etag
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLine, Stock
from apps.purchasing.services.delivery_receipt_service import (
    ReceiptAllocationRequest,
    ReceiptLineRequest,
    process_delivery_receipt,
)


def make_purchase_order(
    *,
    supplier: Company | None = None,
    created_by: Staff | None = None,
    status: str = "draft",
    reference: str | None = None,
) -> PurchaseOrder:
    """Create a PO through the real save path (the model numbers it)."""
    return PurchaseOrder.objects.create(
        supplier=supplier, created_by=created_by, status=status, reference=reference
    )


def make_po_line(  # noqa: PLR0913 -- a factory: every field is an axis a test varies
    po: PurchaseOrder,
    *,
    description: str = "Test line",
    quantity: str = "10.00",
    unit_cost: str | None = "25.00",
    job: Job | None = None,
    item_code: str | None = None,
    **extra: object,
) -> PurchaseOrderLine:
    """Create a PO line with sensible defaults."""
    return PurchaseOrderLine.objects.create(
        purchase_order=po,
        description=description,
        quantity=Decimal(quantity),
        unit_cost=Decimal(unit_cost) if unit_cost is not None else None,
        job=job,
        item_code=item_code,
        **extra,
    )


def make_stock(
    job: Job,
    *,
    description: str = "Stock item",
    quantity: str = "10.00",
    unit_cost: str = "25.00",
    source: str = "manual",
    **extra: object,
) -> Stock:
    """Create a Stock row through the real save path."""
    return Stock.objects.create(
        job=job,
        description=description,
        quantity=Decimal(quantity),
        unit_cost=Decimal(unit_cost),
        source=source,
        **extra,
    )


def receive_po_line(
    line: PurchaseOrderLine, quantity: Decimal, job: Job, stock_holding_job: Job, staff: Staff
) -> PurchaseOrder:
    """Receipt a line equally into stock and a job through the ETag-checked service."""
    po = PurchaseOrder.objects.get(pk=line.purchase_order_id)
    return process_delivery_receipt(
        po.id,
        {
            str(line.id): ReceiptLineRequest(
                total_received=quantity,
                allocations=[
                    ReceiptAllocationRequest(
                        job_id=target.id, quantity=quantity / 2, retail_rate=None, metadata={}
                    )
                    for target in (job, stock_holding_job)
                ],
            )
        },
        staff,
        if_match=purchase_order_etag(po),
    )
