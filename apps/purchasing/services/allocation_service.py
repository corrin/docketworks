"""The allocation concept: materialise, inspect and reverse PO-line allocations.

A purchase-order line's received quantity is allocated either to *stock* (a
``Stock`` row on the stock-holding job) or to a *job* (a material ``CostLine``
on that job's actual cost set). This module owns every side of that concept —
creation, read-back, reversal, and the PO status/ETag recompute that follows —
so the receipt flow, the automatic allocation on "fully received", and the
allocation-reversal endpoint cannot drift apart (ADR 0039).

Status recomputation always bumps ``updated_at`` even when the status label is
unchanged: received quantities changed, so ADR 0003 clients must see a new
ETag. A second status-recompute implementation is deliberately absent.
"""

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal
from uuid import UUID

from django.db import transaction
from django.db.models import Exists, F, OuterRef, QuerySet
from django.utils import timezone

from apps.accounts.models import Staff
from apps.core.models import CompanyDefaults
from apps.job.models import Job
from apps.job.models.costing import CostLine, CostSet, lock_costing_jobs
from apps.purchasing.etag import require_current_etag
from apps.purchasing.models import (
    PurchaseOrder,
    PurchaseOrderLine,
    Stock,
    StockMovement,
    StockMovementKind,
)
from apps.purchasing.schemas import AllocationReversalRequest
from apps.purchasing.services.stock_movement_service import (
    MovementContext,
    move_stock,
    receipt_quantity,
    reverse_issue,
)
from apps.purchasing.tasks import queue_metadata_parse_if_eligible

logger = logging.getLogger(__name__)

AllocationType = Literal["stock", "job"]

STOCK_ALLOCATION: AllocationType = "stock"
JOB_ALLOCATION: AllocationType = "job"


class AllocationReversalError(ValueError):
    """Raised when an allocation cannot be reversed (validation, not a crash)."""


@dataclass(frozen=True, slots=True)
class AllocationMetadata:
    """The stock metadata one receipt allocation resolves to.

    Payload values have three-way semantics:

    - key absent          → inherit the PO line's value
    - key present, blank  → the operator cleared it; store NULL
    - key present, value  → store that value

    Collapsing the first two would hand a cleared field back the ordered value.
    Resolving against the line here (rather than at the write site) keeps the
    rule in one place and leaves the fields plain ``str | None`` (ADR 0028).
    """

    metal_type: str | None
    alloy: str | None
    specifics: str | None
    location: str | None

    @classmethod
    def resolve(cls, payload: Mapping[str, str], line: PurchaseOrderLine) -> "AllocationMetadata":
        """Resolve the payload against ``line`` using the three-way rule."""

        def pick(key: str, line_value: str | None) -> str | None:
            if key not in payload:
                return line_value or None
            return payload[key] or None

        return cls(
            metal_type=pick("metal_type", line.metal_type),
            alloy=pick("alloy", line.alloy),
            specifics=pick("specifics", line.specifics),
            location=pick("location", line.location),
        )

    @classmethod
    def from_line(cls, line: PurchaseOrderLine) -> "AllocationMetadata":
        """Inherit every field from the PO line (automatic allocation)."""
        return cls.resolve({}, line)


@dataclass(frozen=True, slots=True)
class MaterialAllocation:
    """The validated destination, quantity and material details of a receipt."""

    job: Job
    quantity: Decimal
    metadata: AllocationMetadata
    retail_rate_pct: Decimal


@dataclass(frozen=True, slots=True)
class ReversalResult:
    """A recorded reversal or a repeat that made no changes."""

    status: Literal["reversed", "already_reversed"]
    reversed_quantity: Decimal
    description: str
    updated_received_quantity: Decimal
    job_name: str


def retail_pct_to_rate(pct: Decimal) -> Decimal:
    """Convert a retail markup percentage (e.g. 20) to a rate (e.g. 0.2000)."""
    return (pct / Decimal("100")).quantize(Decimal("0.0001"))


def default_retail_rate_pct() -> Decimal:
    """Return the company-default materials markup, as a percentage."""
    return CompanyDefaults.get_solo().materials_markup * 100


def ensure_actual_cost_set(job: Job, staff: Staff) -> CostSet:
    """Return the job's actual cost set, creating rev 1 when it is missing.

    This is the one implementation used by receipts and stock consumption (ADR
    0039).
    """
    existing = job.latest_actual
    if existing is not None:
        return existing
    cost_set = CostSet.objects.create(job=job, kind="actual", rev=1)
    job.latest_actual = cost_set
    job.save(staff=staff, update_fields=["latest_actual"])
    logger.debug("Created missing actual CostSet for job %s", job.id)
    return cost_set


@transaction.atomic
def create_stock_from_allocation(
    *,
    line: PurchaseOrderLine,
    allocation: MaterialAllocation,
    staff: Staff,
) -> Stock:
    """Materialise a received quantity as a stock identity and receipt movement."""
    job, qty = allocation.job, allocation.quantity
    metadata, retail_rate_pct = allocation.metadata, allocation.retail_rate_pct
    if line.unit_cost is None:
        raise ValueError(
            f"Price not confirmed for line {line.id} ({line.description}); "
            f"cannot create a stock allocation."
        )
    stock = Stock(
        job=job,
        description=line.description,
        quantity=Decimal("0"),
        unit_cost=line.unit_cost,
        metal_type=metadata.metal_type,
        alloy=metadata.alloy,
        specifics=metadata.specifics,
        location=metadata.location,
        date=timezone.now(),
        source="purchase_order",
        source_purchase_order_line=line,
    )
    stock.retail_rate = retail_pct_to_rate(retail_rate_pct)
    stock.save()
    move_stock(
        stock,
        qty,
        MovementContext(
            kind=StockMovementKind.RECEIPT,
            reason=f"Receipt against PO line {line.id}",
            actor=staff,
        ),
    )
    # A receipt line often
    # carries only a description, so the row gets the same one-shot LLM
    # enrichment as a hand-entered one. No-op when the metadata came through.
    queue_metadata_parse_if_eligible(stock)
    logger.info("Created Stock %s for line %s, job %s, qty %s.", stock.id, line.id, job.id, qty)
    return stock


@transaction.atomic
def create_costline_from_allocation(  # noqa: PLR0913 -- Allocation inputs stay explicit and keyword-only.
    *,
    purchase_order: PurchaseOrder,
    line: PurchaseOrderLine,
    job: Job,
    qty: Decimal,
    retail_rate_pct: Decimal,
    staff: Staff,
) -> CostLine:
    """Materialise a received quantity as a material CostLine on a job."""
    if line.unit_cost is None:
        raise ValueError(
            f"Price not confirmed for line {line.id} ({line.description}); "
            f"cannot create a job allocation."
        )
    lock_costing_jobs([job.id])
    rate = retail_pct_to_rate(retail_rate_pct)
    unit_revenue = (line.unit_cost * (Decimal("1") + rate)).quantize(Decimal("0.01"))

    # Shop jobs don't bill customers, so revenue must be zero. Stock consumed
    # on customer jobs prices its revenue in consume_stock() instead.
    if job.shop_job:
        unit_revenue = Decimal("0.00")

    cost_set = ensure_actual_cost_set(job, staff)
    cost_line = CostLine(
        cost_set=cost_set,
        kind="material",
        desc=line.description,
        quantity=qty,
        unit_cost=line.unit_cost,
        unit_rev=unit_revenue,
        accounting_date=timezone.localdate(),
        ext_refs={
            "purchase_order_line_id": str(line.id),
            "purchase_order_id": str(purchase_order.id),
        },
        meta={
            "source": "delivery_receipt",
            "retail_rate": float(rate),
            "po_number": purchase_order.po_number,
        },
    )
    cost_line.managed_by = "stock"
    cost_line.save()
    stock = create_stock_from_allocation(
        line=line,
        allocation=MaterialAllocation(
            Stock.get_stock_holding_job(), qty, AllocationMetadata.from_line(line), retail_rate_pct
        ),
        staff=staff,
    )
    move_stock(
        stock,
        -qty,
        MovementContext(
            kind=StockMovementKind.ISSUE,
            reason=f"Receipt allocated to job from PO {purchase_order.po_number}",
            actor=staff,
            counterpart_job=job,
            cost_line=cost_line,
        ),
    )
    logger.info(
        "Created CostLine %s for line %s, job %s, qty %s, retail rate %s%%.",
        cost_line.id,
        line.id,
        job.id,
        qty,
        retail_rate_pct,
    )
    return cost_line


def recompute_purchase_order_status(po: PurchaseOrder) -> None:
    """Derive the PO status from its line totals and bump ``updated_at``.

    Always writes: the received quantities moved, so the ADR 0003 ETag must
    move with them even when the status label is unchanged.
    """
    if not po.po_lines.filter(received_quantity__gt=0).exists():
        new_status = "deleted" if po.status == "deleted" else "submitted"
    elif po.po_lines.filter(received_quantity__lt=F("quantity")).exists():
        new_status = "partially_received"
    else:
        new_status = "fully_received"

    updated_fields = ["updated_at"]
    if new_status != po.status:
        po.status = new_status
        updated_fields.append("status")
        logger.debug("Updated PO %s status to %s", po.po_number, po.status)
    else:
        logger.debug("PO %s status unchanged: %s", po.po_number, po.status)

    po.updated_at = timezone.now()
    po.save(update_fields=updated_fields)


# ── Reads and reversals ────────────────────────────────────────────────────


def consuming_cost_lines(stock_id: UUID) -> QuerySet[CostLine]:
    """Find issued job charges through their protected movement links."""
    return CostLine.objects.filter(
        stockmovement__stock_id=stock_id, stockmovement__kind__in=["issue", "job_opening"]
    )


def _get_po_or_error(po_id: UUID) -> PurchaseOrder:
    """Lock and return the PO; the caller owns the transaction.

    Opus: the row is locked here rather than read plainly because the caller
    checks the ETag against it and then writes. An unlocked read reproduces the
    check-then-write race purchase_order_service.update_purchase_order
    documents as forbidden -- two reversals could both pass the precondition and
    both decrement received_quantity.

    Only a caller inside ``transaction.atomic()`` may use this: Django refuses
    ``select_for_update`` in autocommit, and this project sets no
    ``ATOMIC_REQUESTS``, so a read path calling it raises
    ``TransactionManagementError`` in production. Tests do not see that —
    pytest wraps each one in a transaction — so a read must take
    ``_read_po_or_error`` instead, and the two are kept apart for that reason
    rather than as a performance nicety.
    """
    po = PurchaseOrder.objects.select_for_update(of=("self",)).filter(id=po_id).first()
    if po is None:
        raise AllocationReversalError(f"Purchase Order {po_id} not found")
    return po


def _read_po_or_error(po_id: UUID) -> PurchaseOrder:
    """Return the PO without locking it, for callers that only read."""
    po = PurchaseOrder.objects.filter(id=po_id).first()
    if po is None:
        raise AllocationReversalError(f"Purchase Order {po_id} not found")
    return po


def _get_stock_or_error(po: PurchaseOrder, stock_id: UUID) -> Stock:
    stock = (
        Stock.objects.select_related("source_purchase_order_line", "job")
        .filter(
            id=stock_id,
            source="purchase_order",
            source_purchase_order_line__purchase_order=po,
        )
        .first()
    )
    if stock is None:
        raise AllocationReversalError(
            f"Stock allocation {stock_id} not found or not from PO {po.id}"
        )
    return stock


def _get_costline_or_error(po: PurchaseOrder, cost_line_id: UUID) -> CostLine:
    """Resolve a received job position through its canonical typed provenance."""
    cost_line = (
        CostLine.objects.select_related(
            "cost_set__job", "stockmovement__stock__source_purchase_order_line"
        )
        .filter(
            id=cost_line_id,
            stockmovement__kind__in=["issue", "job_opening"],
            stockmovement__stock__source_purchase_order_line__purchase_order=po,
            ext_refs__purchase_order_id=str(po.id),
        )
        .first()
    )
    if cost_line is None:
        raise AllocationReversalError(f"Job allocation {cost_line_id} not found on PO {po.id}")
    return cost_line


def _decrement_received(po_line: PurchaseOrderLine, quantity: Decimal) -> None:
    """Reverse a recorded allocation without hiding inconsistent receipt totals."""
    changed = PurchaseOrderLine.objects.filter(
        id=po_line.id, received_quantity__gte=quantity
    ).update(received_quantity=F("received_quantity") - quantity)
    if not changed:
        raise AllocationReversalError("The allocation exceeds the recorded received quantity.")
    po_line.refresh_from_db(fields=["received_quantity"])


@transaction.atomic
def reverse_allocation(
    *,
    po_id: UUID,
    line_id: UUID,
    allocation: AllocationReversalRequest,
    if_match: str,
    staff: Staff,
) -> tuple[PurchaseOrder, ReversalResult]:
    """Reverse a receipt once, retaining its stock and any original job charge.

    The locked PO serializes receipt corrections. An already recorded reversal
    can acknowledge a lost-response retry; a new reversal requires the current
    PO version before any quantity or cost changes.
    """
    po = _get_po_or_error(po_id)
    cost_line = None
    if allocation.allocation_type == STOCK_ALLOCATION:
        stock = _get_stock_or_error(po, allocation.allocation_id)
    else:
        cost_line = _get_costline_or_error(po, allocation.allocation_id)
        stock = cost_line.stockmovement.stock
    if stock.source_purchase_order_line_id != line_id:
        raise AllocationReversalError("The allocation does not belong to this purchase order line.")
    po_line = PurchaseOrderLine.objects.select_for_update().get(id=line_id, purchase_order=po)
    receipt = stock.movements.get(kind__in=["receipt", "receipt_opening"])
    already_reversed = StockMovement.objects.filter(reverses=receipt).exists()
    quantity = Decimal("0") if already_reversed else receipt_quantity(receipt)
    job_name = (
        cost_line.cost_set.job.name if cost_line is not None else Stock.STOCK_HOLDING_JOB_NAME
    )

    if not already_reversed:
        require_current_etag(po, if_match)
        if cost_line is not None:
            lock_costing_jobs([cost_line.cost_set.job_id])
            locked_line = CostLine.objects.select_for_update().get(id=cost_line.id)
            reverse_issue(locked_line.stockmovement, staff, "Reverse job receipt allocation")
        _decrement_received(po_line, quantity)
        move_stock(
            stock,
            -quantity,
            MovementContext(
                kind=StockMovementKind.RECEIPT_REVERSAL,
                reason=f"Reverse receipt allocation from PO line {po_line.id}",
                actor=staff,
                reverses=receipt,
            ),
        )
        recompute_purchase_order_status(po)
    return po, ReversalResult(
        status="already_reversed" if already_reversed else "reversed",
        reversed_quantity=quantity,
        description=stock.description,
        updated_received_quantity=po_line.received_quantity,
        job_name=job_name,
    )


def _reversed_stock_ids(po: PurchaseOrder) -> set[UUID]:
    """Read receipt corrections once for an allocation response."""
    return set(
        StockMovement.objects.filter(
            kind=StockMovementKind.RECEIPT_REVERSAL,
            stock__source_purchase_order_line__purchase_order=po,
        ).values_list("stock_id", flat=True)
    )


def get_allocation_details(
    *,
    po_id: UUID,
    allocation_type: AllocationType,
    allocation_id: UUID,
) -> dict[str, object]:
    """Describe one allocation (used by the reversal-confirmation dialog)."""
    po = _read_po_or_error(po_id)
    reversed_ids = _reversed_stock_ids(po)

    if allocation_type == STOCK_ALLOCATION:
        stock_item = _get_stock_or_error(po, allocation_id)
        consuming = consuming_cost_lines(stock_item.id)
        consumed_count = consuming.count()
        return {
            "type": "stock",
            "id": str(stock_item.id),
            "description": stock_item.description,
            "quantity": float(stock_item.quantity),
            "job_name": stock_item.job.name if stock_item.job else "",
            "can_reverse": stock_item.id not in reversed_ids,
            "consumed_by_jobs": consumed_count,
            # Location is optional on Stock, hence the display fallback.
            "location": stock_item.location or "Not specified",
        }

    cost_line = _get_costline_or_error(po, allocation_id)
    return {
        "type": "job",
        "id": str(cost_line.id),
        "description": cost_line.desc,
        "quantity": float(cost_line.quantity),
        "job_name": cost_line.cost_set.job.name,
        "can_reverse": cost_line.stockmovement.stock_id not in reversed_ids,
        "unit_cost": float(cost_line.unit_cost),
        "unit_revenue": float(cost_line.unit_rev),
    }


def list_allocations(po: PurchaseOrder) -> dict[str, list[dict[str, object]]]:
    """Group every existing allocation for ``po`` by PO-line id."""
    reversed_ids = _reversed_stock_ids(po)
    cost_lines = CostLine.objects.filter(
        stockmovement__kind__in=["issue", "job_opening"],
        stockmovement__stock__source_purchase_order_line__purchase_order=po,
        ext_refs__purchase_order_id=str(po.id),
    ).select_related("cost_set__job", "stockmovement__stock")
    stock_items = (
        Stock.objects.filter(
            source="purchase_order",
            source_purchase_order_line__purchase_order_id=po.id,
        )
        .exclude(Exists(cost_lines.filter(stockmovement__stock_id=OuterRef("pk"))))
        .select_related("job", "source_purchase_order_line")
    )

    allocations: dict[str, list[dict[str, object]]] = {}

    for cost_line in cost_lines:
        line_id = str(cost_line.stockmovement.stock.source_purchase_order_line_id)
        retail_rate = cost_line.meta.get("retail_rate")
        allocations.setdefault(line_id, []).append(
            {
                "type": "job",
                "job_id": str(cost_line.cost_set.job.id),
                "job_name": cost_line.cost_set.job.name,
                "quantity": float(cost_line.quantity),
                "retail_rate": float(str(retail_rate)) * 100 if retail_rate else 0,
                "allocation_date": cost_line.created_at,
                "description": cost_line.desc,
                "allocation_id": str(cost_line.id),
                "reversed": cost_line.stockmovement.stock_id in reversed_ids,
            }
        )

    stock_holding_name = Stock.STOCK_HOLDING_JOB_NAME
    for stock_item in stock_items:
        line_id = str(stock_item.source_purchase_order_line_id)
        job = stock_item.job
        if job is None:
            # Opus: not tolerated on read. Receipt stock is only ever created on
            # the stock-holding job -- _materialise routes any other job to a
            # cost line instead -- so a purchase-order stock row without a job is
            # malformed data, not a shape callers should handle. Serving None
            # would encode it as valid (ADR 0015, ADR 0028). The nullable column
            # exists for the Xero item catalogue, which shares this table and
            # holds no job at all; separating the two is what makes it non-null.
            raise ValueError(
                f"Stock {stock_item.id} was received against a purchase order but holds no job"
            )
        # An unpriced row has no markup to report; do not call retail_rate when
        # unit_cost is zero or unset.
        priced = bool(stock_item.unit_revenue) and stock_item.unit_cost > 0
        allocations.setdefault(line_id, []).append(
            {
                "type": "stock",
                "job_id": str(job.id),
                "job_name": "Stock" if job.name == stock_holding_name else job.name,
                "quantity": float(stock_item.quantity),
                "retail_rate": float(stock_item.retail_rate * 100) if priced else 0,
                "allocation_date": stock_item.date,
                "description": stock_item.description,
                "stock_location": stock_item.location or "Not specified",
                "metal_type": stock_item.metal_type,
                "alloy": stock_item.alloy or "",
                "specifics": stock_item.specifics or "",
                "allocation_id": str(stock_item.id),
                "reversed": stock_item.id in reversed_ids,
            }
        )

    logger.info(
        "Found %s allocations across %s lines for PO %s",
        sum(len(rows) for rows in allocations.values()),
        len(allocations),
        po.id,
    )
    return allocations
