"""Purchase-order reads and writes, with ETag optimistic concurrency (ADR 0003).

The PO ETag helper lives here because this module owns the PurchaseOrder
concept. The delivery-receipt flow imports it so both mutation paths compare
the same token.

Optimistic concurrency: ``update_purchase_order`` re-reads the row under
``select_for_update`` and raises ``PreconditionFailedError`` (→ 412) when the
caller's ``If-Match`` does not name the current version. The API layer answers
428 when the header is missing at all.
"""

import logging
from datetime import date
from decimal import Decimal
from typing import TypedDict
from uuid import UUID

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Count, IntegerField, Q
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Cast, Substr
from django.http import Http404
from django.utils import timezone

from apps.accounts.models import Staff
from apps.company.models import Company, Supplier, SupplierPickupAddress
from apps.company.services.company_rest_service import pickup_address_data
from apps.core.models import CompanyDefaults
from apps.core.pagination import paginate
from apps.core.patching import apply_patch_fields
from apps.job.models import Job
from apps.job.models.costing import CostLine
from apps.purchasing.etag import require_current_etag
from apps.purchasing.models import (
    PurchaseOrder,
    PurchaseOrderEvent,
    PurchaseOrderLine,
    Stock,
)
from apps.purchasing.schemas import PurchaseOrderStatus
from apps.purchasing.services.allocation_service import (
    AllocationMetadata,
    create_costline_from_allocation,
    create_stock_from_allocation,
    default_retail_rate_pct,
)
from apps.purchasing.tasks import queue_purchase_order_push

logger = logging.getLogger(__name__)


# ── Read shapes ──────────────────────────────────────────────────────────


class PurchaseOrderJobData(TypedDict):
    """Data contract for PurchaseOrderJobData."""

    job_number: str
    name: str
    company: str


class PurchaseOrderListData(TypedDict):
    """Data contract for PurchaseOrderListData."""

    id: UUID
    po_number: str
    status: str
    order_date: date
    supplier: str
    supplier_id: UUID | None
    created_by_id: UUID | None
    created_by_name: str
    jobs: list[PurchaseOrderJobData]


class PurchaseOrderListPage(TypedDict):
    """One page of PO list rows in the shared envelope (apps/core/pagination)."""

    results: list[PurchaseOrderListData]
    count: int
    page: int
    page_size: int
    total_pages: int


class PurchaseOrderLineData(TypedDict):
    """Data contract for PurchaseOrderLineData."""

    id: UUID
    description: str
    quantity: Decimal
    dimensions: str | None
    unit_cost: Decimal | None
    price_tbc: bool
    supplier_item_code: str | None
    item_code: str | None
    received_quantity: Decimal
    metal_type: str | None
    alloy: str | None
    specifics: str | None
    location: str | None
    job_id: UUID | None
    job_number: int | None
    company_name: str | None
    job_name: str | None
    times_used: int


def _purchase_order_search_filter(query: str) -> Q:
    """Match ``query`` against the three things an operator searches a PO by.

    Opus: job number is matched only when the query is all digits. Casting the
    integer column to text to allow icontains would forfeit its index on every
    search, and no operator searches a job by a fragment of its number.
    """
    matches = Q(po_number__icontains=query) | Q(supplier__name__icontains=query)
    if query.isdigit():
        matches |= Q(po_lines__job__job_number=int(query))
    return matches


def list_purchase_orders(
    *, status_filter: str | None, query: str, page: int, page_size: int
) -> PurchaseOrderListPage:
    """One page of purchase orders with their distinct jobs.

    ``status_filter`` is the comma-separated ``?status=`` query value. Both the
    filter and the search run in the database: production holds 990 orders over
    2,315 lines, so returning them all — which is what reading every row and
    filtering in Python amounted to — is not a page any client can use (ADR
    0054).
    """
    purchase_orders = (
        PurchaseOrder.objects.select_related("supplier", "created_by")
        .prefetch_related("po_lines__job__company")
        .order_by("-created_at")
    )
    if status_filter:
        purchase_orders = purchase_orders.filter(
            status__in={value.strip() for value in status_filter.split(",")}
        )
    trimmed = query.strip()
    if trimmed:
        # distinct() because the job-number branch joins po_lines, which
        # multiplies a PO by its matching lines.
        purchase_orders = purchase_orders.filter(_purchase_order_search_filter(trimmed)).distinct()

    page_data = paginate(purchase_orders, page=page, page_size=page_size)

    rows: list[PurchaseOrderListData] = []
    for po in page_data.rows:
        seen_jobs: dict[UUID, PurchaseOrderJobData] = {}
        for line in po.po_lines.all():
            if line.job and line.job.id not in seen_jobs:
                seen_jobs[line.job.id] = {
                    "job_number": str(line.job.job_number),
                    "name": line.job.name,
                    "company": line.job.company.name if line.job.company else "",
                }
        rows.append(
            {
                "id": po.id,
                "po_number": po.po_number,
                "status": po.status,
                "order_date": po.order_date,
                "supplier": po.supplier.name if po.supplier else "",
                "supplier_id": po.supplier_id,
                "created_by_id": po.created_by_id,
                "created_by_name": po.created_by_name or "",
                "jobs": sorted(seen_jobs.values(), key=lambda job: job["job_number"]),
            }
        )
    return {
        "results": rows,
        "count": page_data.count,
        "page": page_data.page,
        "page_size": page_data.page_size,
        "total_pages": page_data.total_pages,
    }


def _material_usage_counts(item_codes: list[str]) -> dict[str, int]:
    """Count material cost lines per ``meta.item_code`` (the "times used" badge)."""
    if not item_codes:
        return {}
    rows = (
        CostLine.objects.filter(kind="material", meta__item_code__in=item_codes)
        .values_list("meta__item_code")
        .annotate(count=Count("id"))
    )
    return dict(rows)


def purchase_order_line_data(
    line: PurchaseOrderLine, usage_counts: dict[str, int]
) -> PurchaseOrderLineData:
    """Serialise one PO line."""
    job = line.job
    return {
        "id": line.id,
        "description": line.description,
        "quantity": line.quantity,
        "dimensions": line.dimensions,
        "unit_cost": line.unit_cost,
        "price_tbc": line.price_tbc,
        "supplier_item_code": line.supplier_item_code,
        "item_code": line.item_code,
        "received_quantity": line.received_quantity,
        "metal_type": line.metal_type,
        "alloy": line.alloy,
        "specifics": line.specifics,
        "location": line.location,
        "job_id": job.id if job else None,
        "job_number": job.job_number if job else None,
        "company_name": (job.company.name if job and job.company else None),
        "job_name": job.name if job else None,
        "times_used": usage_counts.get(line.item_code or "", 0) if line.item_code else 0,
    }


def purchase_order_detail_data(po: PurchaseOrder) -> dict[str, object]:
    """Serialise a PO plus its lines."""
    lines = list(PurchaseOrderLine.objects.filter(purchase_order=po).select_related("job__company"))
    usage_counts = _material_usage_counts([line.item_code for line in lines if line.item_code])
    supplier = po.supplier
    return {
        "id": po.id,
        "po_number": po.po_number,
        "reference": po.reference,
        "status": po.status,
        "order_date": po.order_date,
        "expected_delivery": po.expected_delivery,
        "online_url": po.online_url,
        "xero_id": po.xero_id,
        "pickup_address_id": po.pickup_address_id,
        "created_by_id": po.created_by_id,
        "supplier": supplier.name if supplier else "",
        "supplier_id": po.supplier_id,
        "supplier_has_xero_id": bool(supplier and supplier.xero_contact_id is not None),
        # The email composer refuses a supplier with no address, so the screen
        # needs to know before offering the button rather than surfacing a 400.
        "supplier_has_email": bool(supplier and supplier.email),
        "lines": [purchase_order_line_data(line, usage_counts) for line in lines],
        "pickup_address": (pickup_address_data(po.pickup_address) if po.pickup_address else None),
        "created_by_name": po.created_by_name or "",
    }


def get_last_purchase_order_number() -> str | None:
    """Return the highest-numbered PO number under the configured prefix."""
    po_prefix = CompanyDefaults.get_solo().po_prefix
    prefix_len = len(po_prefix)
    latest: str | None = (
        PurchaseOrder.objects.filter(po_number__regex=rf"^{po_prefix}\d+$")
        .annotate(num=Cast(Substr("po_number", prefix_len + 1), IntegerField()))
        .order_by("-num", "-created_at")
        .values_list("po_number", flat=True)
        .first()
    )
    return latest


# ── Writes ───────────────────────────────────────────────────────────────


class PurchaseOrderLineWriteData(TypedDict, total=False):
    """The PO-line fields a create/update payload may carry."""

    id: UUID | None
    job_id: UUID | None
    description: str
    quantity: Decimal
    unit_cost: Decimal | None
    price_tbc: bool
    item_code: str | None
    metal_type: str | None
    alloy: str | None
    specifics: str | None
    location: str | None
    dimensions: str | None


class PurchaseOrderCreateData(TypedDict, total=False):
    """The PO fields a create payload may carry."""

    supplier_id: UUID | None
    pickup_address_id: UUID | None
    reference: str | None
    order_date: date | None
    expected_delivery: date | None
    lines: list[PurchaseOrderLineWriteData]


class PurchaseOrderUpdateData(TypedDict, total=False):
    """The PO fields an update payload may carry (only provided keys present)."""

    supplier_id: UUID | None
    pickup_address_id: UUID | None
    reference: str | None
    expected_delivery: date | None
    status: PurchaseOrderStatus
    lines_to_delete: list[UUID]
    lines: list[PurchaseOrderLineWriteData]


#: Line columns a client may write. Everything else on the row is derived
#: (received_quantity, timestamps) or structural (purchase_order).
_LINE_WRITABLE_FIELDS = frozenset(
    {
        "description",
        "job_id",
        "quantity",
        "item_code",
        "metal_type",
        "alloy",
        "specifics",
        "location",
        "dimensions",
    }
)


def _apply_line_fields(line: PurchaseOrderLine, line_data: PurchaseOrderLineWriteData) -> None:
    """Write the supplied line fields onto ``line`` per the PATCH contract.

    ``apps.core.patching`` owns the partial-update rule: only supplied keys
    are written. Values arrive already validated — the schema declares nullable
    text fields nullable-and-nonblank, so ``""`` never reaches here (KAN-329)
    and ``null`` is how a client clears one. No coercion shim, and a new
    nullable field needs no change in this function.

    ``price_tbc`` and ``unit_cost`` need ordering the generic pass cannot
    express, so they are handled here: the flag lands first, then a supplied
    cost consults the line's effective flag, because ``price_tbc`` means "no
    unit cost" (the field's own help_text). Each is still written only when its
    own key is present, so toggling the checkbox never disturbs a stored cost.
    """
    apply_patch_fields(line, dict(line_data), fields=_LINE_WRITABLE_FIELDS)
    if "price_tbc" in line_data:
        line.price_tbc = bool(line_data["price_tbc"])
    if "unit_cost" in line_data:
        line.unit_cost = None if line.price_tbc else line_data["unit_cost"]


def _write_lines(po: PurchaseOrder, lines: list[PurchaseOrderLineWriteData]) -> None:
    """Update lines that carry an id; create the rest."""
    existing = {line.id: line for line in po.po_lines.all()}
    for line_data in lines:
        line_id = line_data.get("id")
        if line_id is None:
            new_line = PurchaseOrderLine(purchase_order=po, description="", quantity=Decimal("0"))
            _apply_line_fields(new_line, line_data)
            new_line.save()
            logger.info("Created new line %s for PO %s", new_line.id, po.id)
            continue
        if line_id not in existing:
            raise DjangoValidationError(f"Line ID {line_id} not found on PO {po.po_number}")
        line = existing[line_id]
        _apply_line_fields(line, line_data)
        line.save()


def _resolve_supplier(supplier_id: UUID) -> Company:
    """Resolve the PO's supplier. ``Supplier`` is a proxy of ``Company``."""
    supplier = Supplier.objects.filter(id=supplier_id).first()
    if supplier is None:
        raise DjangoValidationError(f"Supplier {supplier_id} not found")
    return supplier


def _resolve_pickup_address(pickup_address_id: UUID, supplier: Company) -> SupplierPickupAddress:
    """Resolve a pickup address that belongs to the PO's supplier.

    Fable: ownership is checked here rather than trusted from the client
    because the address list the screen offers is per supplier; an id from
    another company can only arrive by mistake or by hand, and either way a
    PO collecting from a stranger's yard is wrong data, not a preference.
    """
    address = SupplierPickupAddress.objects.filter(
        id=pickup_address_id, company=supplier, is_active=True
    ).first()
    if address is None:
        raise DjangoValidationError(
            f"Pickup address {pickup_address_id} does not belong to supplier {supplier.name}"
        )
    return address


def create_purchase_order(
    data: PurchaseOrderCreateData, *, created_by: Staff | None = None
) -> PurchaseOrder:
    """Create a PO (and its lines); the model generates the PO number."""
    supplier_id = data.get("supplier_id")
    supplier = _resolve_supplier(supplier_id) if supplier_id else None

    pickup_address: SupplierPickupAddress | None
    if "pickup_address_id" in data:
        # Sent, so the client chose: an id, or null for none (ADR 0040).
        pickup_address_id = data["pickup_address_id"]
        if pickup_address_id is None:
            pickup_address = None
        elif supplier is None:
            raise DjangoValidationError("A pickup address needs a supplier")
        else:
            pickup_address = _resolve_pickup_address(pickup_address_id, supplier)
    elif supplier is not None:
        # Not sent: the supplier's primary address, if it has one.
        pickup_address = SupplierPickupAddress.objects.filter(
            company=supplier, is_primary=True, is_active=True
        ).first()
    else:
        pickup_address = None

    with transaction.atomic():
        po = PurchaseOrder.objects.create(
            supplier=supplier,
            pickup_address=pickup_address,
            reference=data.get("reference"),
            order_date=data.get("order_date") or timezone.localdate(),
            # A missing expected-delivery date defaults to today rather than NULL.
            expected_delivery=data.get("expected_delivery") or timezone.localdate(),
            created_by=created_by,
        )
        _write_lines(po, data.get("lines", []))
    return po


def _auto_allocate_line(line: PurchaseOrderLine, po: PurchaseOrder, staff: Staff) -> None:
    """Allocate a whole line automatically when a PO is marked fully received."""
    stock_job = Stock.get_stock_holding_job()
    retail_rate_pct = default_retail_rate_pct()

    if line.job_id is None or line.job_id == stock_job.id:
        already_stocked = Stock.objects.filter(
            source="purchase_order", source_purchase_order_line=line
        ).exists()
        if already_stocked:
            return
        create_stock_from_allocation(
            line=line,
            job=stock_job,
            qty=line.quantity,
            metadata=AllocationMetadata.from_line(line),
            retail_rate_pct=retail_rate_pct,
        )
        line.received_quantity = line.quantity
        line.save()
        return

    job = Job.objects.get(id=line.job_id)
    already_costed = (
        CostLine.objects.annotate(
            source_po_line_id=KeyTextTransform("purchase_order_line_id", "ext_refs"),
        )
        .filter(source_po_line_id=str(line.id))
        .exists()
    )
    if already_costed:
        return

    create_costline_from_allocation(
        purchase_order=po,
        line=line,
        job=job,
        qty=line.quantity,
        retail_rate_pct=retail_rate_pct,
        staff=staff,
    )
    line.received_quantity = line.quantity
    line.save()
    # Bump the job's updated_at without recording a JobEvent.
    Job.objects.filter(pk=job.pk).untracked_update(updated_at=timezone.now())


def _apply_purchase_order_fields(
    po: PurchaseOrder, data: PurchaseOrderUpdateData, staff: Staff
) -> None:
    if "reference" in data:
        po.reference = data["reference"]
    if "expected_delivery" in data:
        po.expected_delivery = data.get("expected_delivery")
    if "status" not in data:
        return

    new_status = data["status"]
    logger.info("Updating PO %s status: %s -> %s", po.po_number, po.status, new_status)
    po.status = new_status
    if new_status != "fully_received":
        return
    for line in po.po_lines.filter(quantity__gt=0):
        _auto_allocate_line(line, po, staff)


def update_purchase_order(
    po_id: UUID,
    data: PurchaseOrderUpdateData,
    *,
    staff: Staff,
    if_match: str,
) -> PurchaseOrder:
    """Update a PO under ``select_for_update`` with an ETag precondition.

    ADR 0003: the comparison and the write happen inside one transaction with
    the row locked, so a check-then-write race cannot slip through.
    """
    with transaction.atomic():
        po = (
            PurchaseOrder.objects.select_for_update(of=("self",))
            .select_related("supplier")
            .filter(id=po_id)
            .first()
        )
        if po is None:
            raise Http404(f"PurchaseOrder {po_id} not found")

        require_current_etag(po, if_match)

        lines_to_delete = data.get("lines_to_delete")
        if lines_to_delete:
            PurchaseOrderLine.objects.filter(id__in=lines_to_delete, purchase_order=po).delete()

        supplier_id = data.get("supplier_id")
        if supplier_id and supplier_id != po.supplier_id:
            po.supplier = _resolve_supplier(supplier_id)
            # The old supplier's yard is no collection point for the new one.
            po.pickup_address = None
        if "pickup_address_id" in data:
            pickup_address_id = data["pickup_address_id"]
            if pickup_address_id is None:
                po.pickup_address = None
            elif po.supplier is None:
                raise DjangoValidationError("A pickup address needs a supplier")
            else:
                po.pickup_address = _resolve_pickup_address(pickup_address_id, po.supplier)

        _write_lines(po, data.get("lines", []))
        _apply_purchase_order_fields(po, data, staff)

        po.save()
        po.refresh_from_db()
        # Xero holds a copy of this order so the supplier's bill has something
        # to reconcile against; keeping that copy current is the system's job,
        # not an operator's. Queued after the write, on commit.
        queue_purchase_order_push(po)
        return po


# ── Events ───────────────────────────────────────────────────────────────


class PurchaseOrderEventData(TypedDict):
    """Data contract for PurchaseOrderEventData."""

    id: UUID
    description: str
    timestamp: object
    staff: str


def purchase_order_event_data(event: PurchaseOrderEvent) -> PurchaseOrderEventData:
    """Serialise one PO event."""
    return {
        "id": event.id,
        "description": event.description,
        "timestamp": event.timestamp,
        "staff": event.staff.get_display_full_name(),
    }


def list_purchase_order_events(po: PurchaseOrder) -> list[PurchaseOrderEventData]:
    """List a PO's events, newest first (model default ordering)."""
    return [purchase_order_event_data(event) for event in po.events.select_related("staff").all()]


def create_purchase_order_event(
    po: PurchaseOrder, description: str, staff: Staff
) -> PurchaseOrderEvent:
    """Record a manual note on a PO."""
    return PurchaseOrderEvent.objects.create(
        purchase_order=po, staff=staff, description=description
    )
