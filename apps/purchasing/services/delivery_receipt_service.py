"""Delivery receipts: received quantities become Stock rows or job cost lines.

Flow:
  1. Lock the PO and every referenced line, then check the ADR 0003 precondition.
  2. Validate the per-line allocations (totals must reconcile, jobs must exist,
     the line must have a confirmed price).
  3. Replace the line's prior stock rows, add to ``received_quantity``, and
     materialise each allocation via ``allocation_service``.
  4. Recompute the PO status (which also bumps the ETag).

This service only validates and persists receipt effects. It does NOT generate
Xero item codes or push anything to Xero — that surface lives on ``/api/xero/``
and lands in Phase 4.

Concurrency note: the PO id arrives in the request BODY, not the URL. The
frontend concurrency layer special-cases that
(``frontend/src/lib/concurrency/interceptors.ts``) so the right ``If-Match``
still travels with the request; the service compares it exactly as the PO PATCH
path does.
"""

import logging
import uuid
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from django.db import transaction
from django.db.models import F

from apps.accounts.models import Staff
from apps.core.errors import AppErrorContext, InvalidInputError, persist_app_error
from apps.job.models import Job
from apps.purchasing.etag import require_current_etag
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLine, Stock
from apps.purchasing.services.allocation_service import (
    AllocationMetadata,
    consuming_cost_lines,
    create_costline_from_allocation,
    create_stock_from_allocation,
    default_retail_rate_pct,
    recompute_purchase_order_status,
)

logger = logging.getLogger(__name__)

RECEIPTABLE_STATUSES = ("submitted", "partially_received", "fully_received")
ALLOCATION_TOLERANCE = Decimal("0.001")


class DeliveryReceiptValidationError(InvalidInputError):
    """Raised when receipt allocation validation fails."""


@dataclass(frozen=True, slots=True)
class ReceiptAllocation:
    """One validated allocation ready to be materialised."""

    job: Job
    quantity: Decimal
    metadata: AllocationMetadata
    retail_rate_pct: Decimal


@dataclass(frozen=True, slots=True)
class ReceiptAllocationRequest:
    """The caller's allocation for one PO line, before validation."""

    job_id: UUID
    quantity: Decimal
    retail_rate: Decimal | None
    metadata: dict[str, str]


@dataclass(frozen=True, slots=True)
class ReceiptLineRequest:
    """The caller's receipt for one PO line."""

    total_received: Decimal
    allocations: list[ReceiptAllocationRequest]


def _load_po_and_lines(
    purchase_order_id: UUID, line_allocations: dict[str, ReceiptLineRequest]
) -> tuple[PurchaseOrder, dict[str, PurchaseOrderLine]]:
    """Lock the PO and the referenced lines; caller owns the transaction."""
    po = (
        PurchaseOrder.objects.select_for_update(of=("self",))
        .select_related("supplier")
        .filter(id=purchase_order_id)
        .first()
    )
    if po is None:
        raise DeliveryReceiptValidationError(f"PurchaseOrder {purchase_order_id} not found")

    requested_ids = set(line_allocations.keys())
    # Lock each referenced line too, so parallel double-submissions cannot both
    # recreate the same stock entries.
    lines = {
        str(line.id): line
        for line in PurchaseOrderLine.objects.select_for_update().filter(
            id__in=requested_ids, purchase_order=po
        )
    }
    if len(lines) != len(requested_ids):
        missing = requested_ids - set(lines)
        raise DeliveryReceiptValidationError(
            f"Invalid or mismatched PurchaseOrderLine IDs provided: {missing}"
        )
    return po, lines


def _load_jobs(line_allocations: dict[str, ReceiptLineRequest]) -> dict[str, Job]:
    job_ids = {
        str(alloc.job_id)
        for line_request in line_allocations.values()
        for alloc in line_request.allocations
    }
    jobs = {str(job.id): job for job in Job.objects.filter(id__in=job_ids)}
    if len(jobs) != len(job_ids):
        missing = job_ids - set(jobs)
        raise DeliveryReceiptValidationError(f"Invalid Job IDs provided in allocations: {missing}")
    return jobs


def _validate_and_prepare_allocations(
    *,
    line: PurchaseOrderLine,
    line_request: ReceiptLineRequest,
    jobs_by_id: dict[str, Job],
) -> tuple[Decimal, list[ReceiptAllocation]]:
    """Return the received total and the allocations to materialise."""
    if line.unit_cost is None:
        raise DeliveryReceiptValidationError(
            f"Price not confirmed for line {line.id} ({line.description}); "
            f"cannot process delivery receipt."
        )

    default_pct = default_retail_rate_pct()
    prepared: list[ReceiptAllocation] = []
    allocated = Decimal("0")

    for alloc in line_request.allocations:
        if alloc.quantity == 0:
            continue
        job = jobs_by_id.get(str(alloc.job_id))
        if job is None:
            raise DeliveryReceiptValidationError(
                f"Invalid or missing job_id for non-zero allocation on line {line.id}."
            )
        prepared.append(
            ReceiptAllocation(
                job=job,
                quantity=alloc.quantity,
                metadata=AllocationMetadata.resolve(alloc.metadata, line),
                # Honor the documented snake_case markup field emitted by the
                # request schema.
                retail_rate_pct=alloc.retail_rate if alloc.retail_rate is not None else default_pct,
            )
        )
        allocated += alloc.quantity

    if abs(allocated - line_request.total_received) > ALLOCATION_TOLERANCE:
        raise DeliveryReceiptValidationError(
            f"Allocation mismatch for line '{line.description}' (id {line.id}). "
            f"Total Received={line_request.total_received}, Sum of Allocations={allocated}."
        )
    # Opus: a line receiving nothing is refused rather than ignored. It passes
    # the reconciliation check above (0 == 0) and then reaches
    # _delete_previous_stock_for_line, which clears the line's existing stock and
    # re-materialises nothing -- so submitting every line of a PO, touched or
    # not, destroys the stock of the ones already received while their
    # received_quantity stays put. A caller with nothing to record for a line
    # omits the line.
    if not prepared and line_request.total_received == 0:
        raise DeliveryReceiptValidationError(
            f"Line '{line.description}' (id {line.id}) has nothing to receive; "
            f"omit it from the receipt instead of sending a zero quantity."
        )
    return line_request.total_received, prepared


def _delete_previous_stock_for_line(line: PurchaseOrderLine, *, run_id: str) -> None:
    """Clear the line's prior purchase-order stock before re-materialising it.

    Opus: refuses when a cost line has already consumed one of those rows. The
    allocation-delete path has always refused that case
    (``allocation_service._delete_stock_allocation``); this path did not, so a
    second receipt silently deleted stock that jobs were costed against and left
    their ``ext_refs.stock_id`` pointing at nothing -- an unindexed JSON string
    with no foreign key, so the database could not object either.

    Deleting at all is the wrong primitive: stock should move, never vanish. It
    survives here only because ``unique_active_stock_per_po_line``
    (``models.py``) permits one live row per PO line, leaving re-receipting no
    other option. The movement ledger removes both.
    """
    existing = Stock.objects.filter(source="purchase_order", source_purchase_order_line=line)
    for stock_item in existing:
        consumed_count = consuming_cost_lines(stock_item.id).count()
        if consumed_count:
            raise DeliveryReceiptValidationError(
                f"Line '{line.description}' ({line.id}) has stock consumed by "
                f"{consumed_count} job(s); delete that allocation before receiving again."
            )
    pre_count = existing.count()
    if pre_count:
        logger.warning(
            "delivery_receipt run [%s]: line %s has %s existing stock entries before delete",
            run_id,
            line.id,
            pre_count,
        )
    deleted_count, _ = existing.delete()
    if deleted_count:
        logger.debug(
            "delivery_receipt run [%s]: deleted %s existing stock entries for line %s.",
            run_id,
            deleted_count,
            line.id,
        )


def _materialise(
    *,
    po: PurchaseOrder,
    line: PurchaseOrderLine,
    allocations: list[ReceiptAllocation],
    stock_holding_job_id: UUID,
    staff: Staff,
) -> None:
    for alloc in allocations:
        if alloc.job.id == stock_holding_job_id:
            create_stock_from_allocation(
                line=line,
                job=alloc.job,
                qty=alloc.quantity,
                metadata=alloc.metadata,
                retail_rate_pct=alloc.retail_rate_pct,
            )
        else:
            create_costline_from_allocation(
                purchase_order=po,
                line=line,
                job=alloc.job,
                qty=alloc.quantity,
                retail_rate_pct=alloc.retail_rate_pct,
                staff=staff,
            )


def process_delivery_receipt(
    purchase_order_id: UUID,
    line_allocations: dict[str, ReceiptLineRequest],
    staff: Staff,
    *,
    if_match: str,
) -> PurchaseOrder:
    """Validate and persist a delivery receipt; return the refreshed PO."""
    logger.info("Starting delivery receipt processing for PO ID: %s", purchase_order_id)
    run_id = f"dr-{uuid.uuid4()}"
    try:
        with transaction.atomic():
            po, lines_by_id = _load_po_and_lines(purchase_order_id, line_allocations)
            require_current_etag(po, if_match)

            if po.status not in RECEIPTABLE_STATUSES:
                raise DeliveryReceiptValidationError(
                    f"Cannot process delivery receipt for PO {po.po_number} "
                    f"with status '{po.status}'."
                )

            stock_holding_job_id = Stock.get_stock_holding_job().id
            jobs_by_id = _load_jobs(line_allocations)

            for line_id, line_request in line_allocations.items():
                line = lines_by_id[str(line_id)]
                total_received, prepared = _validate_and_prepare_allocations(
                    line=line, line_request=line_request, jobs_by_id=jobs_by_id
                )

                _delete_previous_stock_for_line(line, run_id=run_id)

                PurchaseOrderLine.objects.filter(id=line.id).update(
                    received_quantity=F("received_quantity") + total_received
                )
                line.refresh_from_db(fields=["received_quantity"])

                _materialise(
                    po=po,
                    line=line,
                    allocations=prepared,
                    stock_holding_job_id=stock_holding_job_id,
                    staff=staff,
                )

            recompute_purchase_order_status(po)
            logger.info(
                "delivery_receipt run [%s]: processed delivery receipt for PO %s",
                run_id,
                po.po_number,
            )
            return po
    except Exception as exc:
        persist_app_error(
            exc,
            AppErrorContext(
                additional_context={
                    "purchase_order_id": str(purchase_order_id),
                    "delivery_receipt_run_id": run_id,
                }
            ),
        )
        logger.exception("Error processing delivery receipt for PO %s", purchase_order_id)
        raise
