import logging
import uuid
from decimal import Decimal
from typing import Dict

from django.db import transaction
from django.db.models import F, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.job.models import CostLine, CostSet, Job
from apps.purchasing.etag import generate_po_etag, normalize_etag
from apps.purchasing.exceptions import PreconditionFailedError
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLine, Stock
from apps.workflow.models.company_defaults import CompanyDefaults
from apps.workflow.services.error_persistence import persist_app_error
from apps.workflow.services.validation import to_decimal

logger = logging.getLogger(__name__)


class DeliveryReceiptValidationError(ValueError):
    """Raised when receipt allocation validation fails."""


def _to_receipt_decimal(value, *, field_label: str) -> Decimal:
    """Validate and convert to Decimal, wrapping errors as delivery receipt errors."""
    try:
        return to_decimal(value, field_label=field_label)
    except ValueError as exc:
        raise DeliveryReceiptValidationError(str(exc)) from exc


def _retail_pct_to_rate(pct: Decimal) -> Decimal:
    """Convert a retail markup percentage (e.g. 20) to a decimal rate (e.g. 0.2000)."""
    return (pct / Decimal("100")).quantize(Decimal("0.0001"))


def _load_po_and_lines(
    purchase_order_id: str, line_allocations: Dict
) -> tuple[PurchaseOrder, dict[str, PurchaseOrderLine]]:
    """
    Fetch and lock the purchase order plus requested lines.

    Caller must already be inside an atomic block; this helper assumes the
    surrounding transaction context (see process_delivery_receipt).
    """
    # Lock the PO row to avoid concurrent requests creating duplicate stock entries
    # before the first transaction commits.
    po = (
        PurchaseOrder.objects.select_for_update(of=("self",))
        .select_related("supplier")
        .get(id=purchase_order_id)
    )
    logger.debug("Found PO %s", po.po_number)

    requested_ids = set(line_allocations.keys())
    # Lock each referenced PO line as well to prevent double submissions running
    # in parallel and recreating the same stock entries.
    line_qs = PurchaseOrderLine.objects.select_for_update().filter(
        id__in=requested_ids, purchase_order=po
    )
    lines = {str(line.id): line for line in line_qs}
    if len(lines) != len(requested_ids):
        missing = requested_ids - set(lines.keys())
        raise DeliveryReceiptValidationError(
            f"Invalid or mismatched PurchaseOrderLine IDs provided: {missing}"
        )
    return po, lines


def _load_jobs(line_allocations: Dict) -> dict[str, Job]:
    job_ids: set[str] = set()
    for line_data in line_allocations.values():
        for alloc in line_data.get("allocations", []):
            jid = alloc.get("job_id")
            if jid:
                job_ids.add(str(jid))
    jobs = {str(j.id): j for j in Job.objects.filter(id__in=job_ids)}
    if len(jobs) != len(job_ids):
        missing = job_ids - set(jobs.keys())
        raise DeliveryReceiptValidationError(
            f"Invalid Job IDs provided in allocations: {missing}"
        )
    return jobs


def _validate_and_prepare_allocations(
    line: PurchaseOrderLine,
    line_data: dict,
    jobs_by_id: dict[str, Job],
) -> tuple[Decimal, list[dict]]:
    """
    Returns (total_received, prepared_allocations).
    Each prepared allocation = {"job": Job, "quantity": Decimal, "metadata": dict, "retail_rate_pct": Decimal}
    """
    if line.unit_cost is None:
        raise DeliveryReceiptValidationError(
            f"Price not confirmed for line {line.id} ({line.description}); "
            f"cannot process delivery receipt."
        )

    total_received = _to_receipt_decimal(
        line_data.get("total_received", 0), field_label=f"line {line.id} total_received"
    )

    defaults = CompanyDefaults.get_solo()
    default_retail_rate_pct = defaults.materials_markup * 100

    prepared: list[dict] = []
    alloc_sum = Decimal("0")

    for alloc in line_data.get("allocations", []):
        qty = _to_receipt_decimal(
            alloc.get("quantity", 0), field_label=f"line {line.id} allocation quantity"
        )
        if qty == 0:
            continue

        job_id = str(alloc.get("job_id"))
        if not job_id or job_id == "None" or job_id not in jobs_by_id:
            raise DeliveryReceiptValidationError(
                f"Invalid or missing job_id for non-zero allocation on line {line.id}."
            )

        retail_rate_pct = Decimal(str(alloc.get("retailRate", default_retail_rate_pct)))

        prepared.append(
            {
                "job": jobs_by_id[job_id],
                "quantity": qty,
                "metadata": alloc.get("metadata", {}),
                "retail_rate_pct": retail_rate_pct,
            }
        )
        alloc_sum += qty

    # Totals must match (allow tiny tolerance, can be refactored)
    if abs(alloc_sum - total_received) > Decimal("0.001"):
        raise DeliveryReceiptValidationError(
            f"Allocation mismatch for line '{line.description}' (id {line.id}). "
            f"Total Received={total_received}, Sum of Allocations={alloc_sum}."
        )

    return total_received, prepared


def _delete_previous_stock_for_line(line: PurchaseOrderLine, *, run_id: str) -> None:
    existing = Stock.objects.filter(
        source="purchase_order", source_purchase_order_line=line
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


def _ensure_actual_costset(job: Job, staff) -> CostSet:
    if job.latest_actual:
        return job.latest_actual
    cs = CostSet.objects.create(job=job, kind="actual", rev=1)
    job.latest_actual = cs
    job.save(staff=staff, update_fields=["latest_actual"])
    logger.debug("Created missing actual CostSet for job %s", job.id)
    return cs


def _create_stock_from_allocation(
    purchase_order: PurchaseOrder,
    line: PurchaseOrderLine,
    job: Job,
    qty: Decimal,
    metadata: dict,
    retail_rate_pct: Decimal,
) -> Stock:
    retail_rate = _retail_pct_to_rate(retail_rate_pct)

    stock = Stock.objects.create(
        job=job,
        description=line.description,
        quantity=qty,
        unit_cost=line.unit_cost,
        retail_rate=retail_rate,
        metal_type=metadata.get("metal_type", line.metal_type or "unspecified"),
        alloy=metadata.get("alloy", line.alloy or ""),
        specifics=metadata.get("specifics", line.specifics or ""),
        location=metadata.get("location", line.location or ""),
        date=timezone.now(),
        source="purchase_order",
        source_purchase_order_line=line,
    )

    # Parse extra metadata
    from apps.quoting.services.stock_parser import auto_parse_stock_item

    auto_parse_stock_item(stock)

    logger.info(
        "Created Stock %s for line %s, job %s, qty %s.", stock.id, line.id, job.id, qty
    )
    return stock


def _create_costline_from_allocation(
    purchase_order: PurchaseOrder,
    line: PurchaseOrderLine,
    job: Job,
    qty: Decimal,
    retail_rate_pct: Decimal,
    staff,
) -> CostLine:
    r = _retail_pct_to_rate(retail_rate_pct)
    unit_revenue = (line.unit_cost * (Decimal("1") + r)).quantize(Decimal("0.01"))

    # Shop jobs don't bill customers, so revenue must be zero.
    # Stock consumed on customer jobs calculates revenue via consume_stock().
    if job.shop_job:
        unit_revenue = Decimal("0.00")

    logger.info(
        "Creating cost line allocation for PO %s line %s (job=%s, qty=%s, unit_cost=%s, markup_pct=%s) -> unit_rev=%s",
        purchase_order.po_number,
        line.id,
        getattr(job, "job_number", None),
        qty,
        line.unit_cost,
        retail_rate_pct,
        unit_revenue,
    )

    cs = _ensure_actual_costset(job, staff)
    cl = CostLine.objects.create(
        cost_set=cs,
        kind="material",
        desc=line.description,
        quantity=qty,
        unit_cost=line.unit_cost,
        unit_rev=unit_revenue,
        accounting_date=timezone.now().date(),
        ext_refs={
            "purchase_order_line_id": str(line.id),
            "purchase_order_id": str(purchase_order.id),
        },
        meta={
            "source": "delivery_receipt",
            "retail_rate": float(r),
            "po_number": purchase_order.po_number,
        },
    )
    logger.info(
        "Created CostLine %s for line %s, job %s, qty %s, retail rate %.2f%%.",
        cl.id,
        line.id,
        job.id,
        qty,
        float(retail_rate_pct),
    )
    return cl


def _recompute_po_status(po: PurchaseOrder) -> None:
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

    updated_fields: list[str] = []
    if new_status != po.status:
        po.status = new_status
        updated_fields.append("status")
        logger.debug("Updated PO %s status to %s", po.po_number, po.status)
    else:
        logger.debug("PO %s status unchanged: %s", po.po_number, po.status)

    po.updated_at = timezone.now()
    updated_fields.append("updated_at")
    po.save(update_fields=updated_fields)


def process_delivery_receipt(
    purchase_order_id: str,
    line_allocations: dict,
    staff,
    *,
    expected_etag: str | None = None,
) -> PurchaseOrder:
    """
    Process a delivery receipt:
      1) Validate PO, lines, jobs, and per-line allocations
      2) For each line: delete prior Stock, increment received_quantity, create Stock/CostLines
      3) Recompute PO status
    SRP: this service only validates and persists receipt effects.
    It does NOT generate Xero item codes or push data to Xero.
    """
    logger.info("Starting delivery receipt processing for PO ID: %s", purchase_order_id)
    logger.debug("Received line_allocations: %s", line_allocations)

    STOCK_HOLDING_JOB_ID = Stock.get_stock_holding_job().id

    run_id = f"dr-{uuid.uuid4()}"
    try:
        with transaction.atomic():
            po, lines_by_id = _load_po_and_lines(purchase_order_id, line_allocations)
            expected_normalized = (
                normalize_etag(expected_etag) if expected_etag else None
            )
            current_etag = normalize_etag(generate_po_etag(po))
            if expected_normalized is not None and expected_normalized != current_etag:
                raise PreconditionFailedError(
                    "Purchase order modified since it was fetched."
                )
            jobs_by_id = _load_jobs(line_allocations)

            if po.status not in ("submitted", "partially_received", "fully_received"):
                raise DeliveryReceiptValidationError(
                    f"Cannot process delivery receipt for PO {po.po_number} "
                    f"with status '{po.status}'."
                )

            # Per-line processing
            for line_id, data in line_allocations.items():
                line = lines_by_id[str(line_id)]
                logger.debug("Processing line %s (%s)", line.id, line.description)

                logger.info(
                    "delivery_receipt run [%s]: line %s incoming payload total_received=%s allocations=%s",
                    run_id,
                    line.id,
                    data.get("total_received"),
                    data.get("allocations"),
                )

                total_received, prepared_allocs = _validate_and_prepare_allocations(
                    line=line,
                    line_data=data,
                    jobs_by_id=jobs_by_id,
                )

                # Delete prior stock entries created from this line
                _delete_previous_stock_for_line(line, run_id=run_id)

                # Increment received_quantity atomically
                PurchaseOrderLine.objects.filter(id=line.id).update(
                    received_quantity=F("received_quantity") + total_received
                )
                line.refresh_from_db(fields=["received_quantity"])
                logger.debug(
                    "Added %s to line %s received_quantity → now %s",
                    total_received,
                    line.id,
                    line.received_quantity,
                )

                # Materialize allocations
                for alloc in prepared_allocs:
                    job = alloc["job"]
                    qty = alloc["quantity"]
                    retail_rate_pct = alloc["retail_rate_pct"]

                    if str(job.id) == str(STOCK_HOLDING_JOB_ID):
                        _create_stock_from_allocation(
                            purchase_order=po,
                            line=line,
                            job=job,
                            qty=qty,
                            metadata=alloc.get("metadata", {}),
                            retail_rate_pct=retail_rate_pct,
                        )
                    else:
                        _create_costline_from_allocation(
                            purchase_order=po,
                            line=line,
                            job=job,
                            qty=qty,
                            retail_rate_pct=retail_rate_pct,
                            staff=staff,
                        )

            _recompute_po_status(po)

            logger.info(
                "delivery_receipt run [%s]: Successfully processed delivery receipt for PO %s",
                run_id,
                po.po_number,
            )
            return po

    except DeliveryReceiptValidationError:
        # Let DRF/view layer convert to proper 4xx; message already specific
        logger.exception(
            "Validation Error processing delivery receipt for PO %s", purchase_order_id
        )
        raise
    except PurchaseOrder.DoesNotExist:
        logger.exception(
            "PO %s not found during delivery receipt processing", purchase_order_id
        )
        raise
    except Exception as e:
        persist_app_error(e)
        logger.exception(
            "Unexpected error processing delivery receipt for PO %s: %s",
            purchase_order_id,
            str(e),
        )
        raise
