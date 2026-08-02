"""The allocation concept: materialise, inspect and delete PO-line allocations.

A purchase-order line's received quantity is allocated either to *stock* (a
``Stock`` row on the stock-holding job) or to a *job* (a material ``CostLine``
on that job's actual cost set). This module owns every side of that concept —
creation, read-back, deletion, and the PO status/ETag recompute that follows —
so the receipt flow, the automatic allocation on "fully received", and the
allocation-delete endpoint cannot drift apart (ADR 0039).

v1 split this across three files with two divergent copies of the status
recompute (``delivery_receipt_service._recompute_po_status`` always bumped
``updated_at``; ``allocation_service._update_po_status`` skipped the write when
the status was unchanged, leaving the PO ETag stale after a delete). v2 keeps
the always-bump behaviour: the PO's received quantities changed, so ADR 0003
clients must see a new ETag.
"""

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal
from uuid import UUID

from django.db import transaction
from django.db.models import F, QuerySet, Sum, Value
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Coalesce, Greatest
from django.utils import timezone

from apps.accounts.models import Staff
from apps.core.errors import AppErrorContext, persist_app_error
from apps.core.models import CompanyDefaults
from apps.job.models import Job
from apps.job.models.costing import CostLine, CostSet
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLine, Stock

logger = logging.getLogger(__name__)

AllocationType = Literal["stock", "job"]

STOCK_ALLOCATION: AllocationType = "stock"
JOB_ALLOCATION: AllocationType = "job"


class AllocationDeletionError(ValueError):
    """Raised when an allocation cannot be deleted (validation, not a crash)."""


@dataclass(frozen=True, slots=True)
class AllocationMetadata:
    """Per-allocation overrides for the stock row a receipt creates.

    v1 passed a bare ``dict`` whose keys were read with ``.get(key, line_value)``
    — a typed record instead (ADR 0028), with the PO line supplying every
    unset field.
    """

    metal_type: str | None = None
    alloy: str | None = None
    specifics: str | None = None
    location: str | None = None

    @classmethod
    def from_payload(cls, payload: dict[str, str]) -> "AllocationMetadata":
        """Build from the receipt payload's free-form metadata dict."""
        return cls(
            metal_type=payload.get("metal_type") or None,
            alloy=payload.get("alloy") or None,
            specifics=payload.get("specifics") or None,
            location=payload.get("location") or None,
        )


@dataclass(frozen=True, slots=True)
class DeletionResult:
    """v1 ``DeletionResult`` — the allocation-delete response payload."""

    success: bool
    message: str
    deleted_quantity: float
    description: str | None
    updated_received_quantity: float
    job_name: str | None = None


def retail_pct_to_rate(pct: Decimal) -> Decimal:
    """Convert a retail markup percentage (e.g. 20) to a rate (e.g. 0.2000)."""
    return (pct / Decimal("100")).quantize(Decimal("0.0001"))


def default_retail_rate_pct() -> Decimal:
    """Return the company-default materials markup, as a percentage."""
    return CompanyDefaults.get_solo().materials_markup * 100


def ensure_actual_cost_set(job: Job, staff: Staff) -> CostSet:
    """Return the job's actual cost set, creating rev 1 when it is missing.

    The ONE implementation (ADR 0039): v1 carried this in both
    ``delivery_receipt_service._ensure_actual_costset`` and ``consume_stock``,
    differing only in whether the summary default was spelled out.
    """
    existing = job.latest_actual
    if existing is not None:
        return existing
    cost_set = CostSet.objects.create(job=job, kind="actual", rev=1)
    job.latest_actual = cost_set
    job.save(staff=staff, update_fields=["latest_actual"])
    logger.debug("Created missing actual CostSet for job %s", job.id)
    return cost_set


def create_stock_from_allocation(
    *,
    line: PurchaseOrderLine,
    job: Job,
    qty: Decimal,
    metadata: AllocationMetadata,
    retail_rate_pct: Decimal,
) -> Stock:
    """Materialise a received quantity as a Stock row on the stock-holding job."""
    if line.unit_cost is None:
        raise ValueError(
            f"Price not confirmed for line {line.id} ({line.description}); "
            f"cannot create a stock allocation."
        )
    stock = Stock(
        job=job,
        description=line.description,
        quantity=qty,
        unit_cost=line.unit_cost,
        metal_type=metadata.metal_type or line.metal_type,
        alloy=metadata.alloy or line.alloy,
        specifics=metadata.specifics or line.specifics,
        location=metadata.location or line.location,
        date=timezone.now(),
        source="purchase_order",
        source_purchase_order_line=line,
    )
    stock.retail_rate = retail_pct_to_rate(retail_rate_pct)
    stock.save()
    logger.info("Created Stock %s for line %s, job %s, qty %s.", stock.id, line.id, job.id, qty)
    return stock


def create_costline_from_allocation(  # noqa: PLR0913 -- v1 signature (all keyword-only)
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
    cost_line.save()
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
    totals = po.po_lines.aggregate(
        ordered=Coalesce(Sum("quantity"), Value(Decimal("0"))),
        received=Coalesce(Sum("received_quantity"), Value(Decimal("0"))),
    )
    ordered, received = totals["ordered"], totals["received"]

    if received <= 0 and po.status != "deleted":
        new_status = "submitted"
    elif received < ordered:
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


# ── Reads and deletes ────────────────────────────────────────────────────


def _consuming_cost_lines(stock_id: UUID) -> QuerySet[CostLine]:
    return CostLine.objects.annotate(
        consumed_stock_id=KeyTextTransform("stock_id", "ext_refs"),
    ).filter(consumed_stock_id=str(stock_id))


def _get_po_or_error(po_id: UUID) -> PurchaseOrder:
    po = PurchaseOrder.objects.filter(id=po_id).first()
    if po is None:
        raise AllocationDeletionError(f"Purchase Order {po_id} not found")
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
        raise AllocationDeletionError(
            f"Stock allocation {stock_id} not found or not from PO {po.id}"
        )
    return stock


def _get_costline_or_error(po: PurchaseOrder, cost_line_id: UUID) -> CostLine:
    """Fetch a PO-sourced CostLine, verifying both ext_refs back-references."""
    cost_line = (
        CostLine.objects.select_related("cost_set__job")
        .annotate(
            source_po_id=KeyTextTransform("purchase_order_id", "ext_refs"),
            source_po_line_id=KeyTextTransform("purchase_order_line_id", "ext_refs"),
        )
        .filter(id=cost_line_id, source_po_id=str(po.id))
        .first()
    )
    if cost_line is None:
        raise AllocationDeletionError(
            f"Job allocation {cost_line_id} not found or not from PO {po.id}"
        )
    if not cost_line.ext_refs.get("purchase_order_line_id"):
        raise AllocationDeletionError(
            f"Cost line {cost_line_id} missing purchase_order_line_id in ext_refs"
        )
    return cost_line


def _resolve_po_line(po: PurchaseOrder, cost_line: CostLine) -> PurchaseOrderLine:
    po_line = PurchaseOrderLine.objects.filter(
        id=cost_line.ext_refs["purchase_order_line_id"], purchase_order=po
    ).first()
    if po_line is None:
        raise AllocationDeletionError(
            f"Purchase Order Line referenced by allocation {cost_line.id} not found"
        )
    return po_line


def _decrement_received(po_line: PurchaseOrderLine, quantity: Decimal) -> None:
    """Take ``quantity`` back off the line's received total, clamped at zero."""
    PurchaseOrderLine.objects.filter(id=po_line.id).update(
        received_quantity=Greatest(Value(Decimal("0")), F("received_quantity") - Value(quantity))
    )
    po_line.refresh_from_db(fields=["received_quantity"])


def _delete_stock_allocation(po_line: PurchaseOrderLine, stock_item: Stock) -> DeletionResult:
    consumed_count = _consuming_cost_lines(stock_item.id).count()
    if consumed_count:
        raise AllocationDeletionError(
            f"Cannot delete stock allocation - stock has been consumed by {consumed_count} job(s)"
        )

    deleted_qty = stock_item.quantity
    desc = stock_item.description
    _decrement_received(po_line, deleted_qty)
    stock_item.delete()

    logger.info(
        "Deleted stock allocation: %s, qty=%s, PO line received now=%s",
        desc,
        deleted_qty,
        po_line.received_quantity,
    )
    return DeletionResult(
        success=True,
        message="Stock allocation deleted successfully",
        deleted_quantity=float(deleted_qty),
        description=desc,
        updated_received_quantity=float(po_line.received_quantity),
        job_name=Stock.get_stock_holding_job().name,
    )


def _delete_job_allocation(po_line: PurchaseOrderLine, cost_line: CostLine) -> DeletionResult:
    deleted_qty = cost_line.quantity
    desc = cost_line.desc
    job_name = cost_line.cost_set.job.name

    _decrement_received(po_line, deleted_qty)
    cost_line.delete()

    logger.info(
        "Deleted job allocation: %s, qty=%s, job=%s, PO line received now=%s",
        desc,
        deleted_qty,
        job_name,
        po_line.received_quantity,
    )
    return DeletionResult(
        success=True,
        message="Job allocation deleted successfully",
        deleted_quantity=float(deleted_qty),
        description=desc,
        updated_received_quantity=float(po_line.received_quantity),
        job_name=job_name,
    )


def delete_allocation(
    *,
    po_id: UUID,
    allocation_type: AllocationType,
    allocation_id: UUID,
) -> DeletionResult:
    """Delete one Stock or CostLine allocation and recompute the PO status.

    ``line_id`` is part of v1's URL but was never used to resolve the
    allocation — the allocation row carries its own PO-line back-reference, and
    trusting the URL instead would let a caller decrement the wrong line. v2
    keeps resolving from the row (the URL segment stays for path parity).
    """
    logger.info(
        "Starting allocation deletion - PO: %s, Type: %s, ID: %s",
        po_id,
        allocation_type,
        allocation_id,
    )
    try:
        with transaction.atomic():
            po = _get_po_or_error(po_id)

            if allocation_type == STOCK_ALLOCATION:
                stock = _get_stock_or_error(po, allocation_id)
                source_line_id = stock.source_purchase_order_line_id
                if source_line_id is None:
                    raise AllocationDeletionError(
                        f"Stock allocation {allocation_id} has no source purchase order line"
                    )
                po_line = PurchaseOrderLine.objects.select_for_update().get(id=source_line_id)
                locked_stock = Stock.objects.select_for_update().get(id=stock.id)
                result = _delete_stock_allocation(po_line, locked_stock)
            else:
                cost_line = _get_costline_or_error(po, allocation_id)
                po_line = PurchaseOrderLine.objects.select_for_update().get(
                    id=_resolve_po_line(po, cost_line).id
                )
                locked_line = (
                    CostLine.objects.select_related("cost_set__job")
                    .select_for_update()
                    .get(id=cost_line.id)
                )
                result = _delete_job_allocation(po_line, locked_line)

            recompute_purchase_order_status(po)
            return result
    except AllocationDeletionError:
        raise
    except Exception as exc:
        persist_app_error(
            exc,
            AppErrorContext(
                additional_context={
                    "po_id": str(po_id),
                    "allocation_type": allocation_type,
                    "allocation_id": str(allocation_id),
                }
            ),
        )
        raise


def get_allocation_details(
    *,
    po_id: UUID,
    allocation_type: AllocationType,
    allocation_id: UUID,
) -> dict[str, object]:
    """Describe one allocation (used by the delete-confirmation dialog)."""
    po = _get_po_or_error(po_id)

    if allocation_type == STOCK_ALLOCATION:
        stock_item = _get_stock_or_error(po, allocation_id)
        consuming = _consuming_cost_lines(stock_item.id)
        consumed_count = consuming.count()
        return {
            "type": "stock",
            "id": str(stock_item.id),
            "description": stock_item.description,
            "quantity": float(stock_item.quantity),
            "job_name": stock_item.job.name if stock_item.job else "",
            "can_delete": consumed_count == 0,
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
        "can_delete": True,
        "unit_cost": float(cost_line.unit_cost),
        "unit_revenue": float(cost_line.unit_rev),
    }


def list_allocations(po: PurchaseOrder) -> dict[str, list[dict[str, object]]]:
    """Group every existing allocation for ``po`` by PO-line id."""
    cost_lines = (
        CostLine.objects.annotate(
            source_po_id=KeyTextTransform("purchase_order_id", "ext_refs"),
        )
        .filter(source_po_id=str(po.id))
        .select_related("cost_set__job")
    )
    stock_items = Stock.objects.filter(
        source="purchase_order",
        source_purchase_order_line__purchase_order_id=po.id,
    ).select_related("job", "source_purchase_order_line")

    allocations: dict[str, list[dict[str, object]]] = {}

    for cost_line in cost_lines:
        line_id = cost_line.ext_refs.get("purchase_order_line_id")
        if not line_id:
            logger.warning(
                "CostLine %s has no purchase_order_line_id in ext_refs: %s",
                cost_line.id,
                cost_line.ext_refs,
            )
            continue
        retail_rate = cost_line.meta.get("retail_rate")
        allocations.setdefault(str(line_id), []).append(
            {
                "type": "job",
                "job_id": str(cost_line.cost_set.job.id),
                "job_name": cost_line.cost_set.job.name,
                "quantity": float(cost_line.quantity),
                "retail_rate": float(str(retail_rate)) * 100 if retail_rate else 0,
                "allocation_date": cost_line.created_at,
                "description": cost_line.desc,
                "allocation_id": str(cost_line.id),
            }
        )

    stock_holding_name = Stock.STOCK_HOLDING_JOB_NAME
    for stock_item in stock_items:
        line_id = str(stock_item.source_purchase_order_line_id)
        job = stock_item.job
        # Stock.retail_rate raises when unit_cost is zero/unset (v1 crashed the
        # whole endpoint there); an unpriced row simply has no markup to report.
        priced = bool(stock_item.unit_revenue) and stock_item.unit_cost > 0
        allocations.setdefault(line_id, []).append(
            {
                "type": "stock",
                "job_id": str(job.id) if job else None,
                "job_name": "Stock"
                if job and job.name == stock_holding_name
                else (job.name if job else ""),
                "quantity": float(stock_item.quantity),
                "retail_rate": float(stock_item.retail_rate * 100) if priced else 0,
                "allocation_date": stock_item.date,
                "description": stock_item.description,
                "stock_location": stock_item.location or "Not specified",
                "metal_type": stock_item.metal_type,
                "alloy": stock_item.alloy or "",
                "specifics": stock_item.specifics or "",
                "allocation_id": str(stock_item.id),
            }
        )

    logger.info(
        "Found %s allocations across %s lines for PO %s",
        sum(len(rows) for rows in allocations.values()),
        len(allocations),
        po.id,
    )
    return allocations
