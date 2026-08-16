"""The purchasing domain's ninja router (thin translators over the services).

The router exposes purchase orders, receipts, allocations, stock, supplier and
job lookup, supplier-price status, and product-mapping review under
``/api/purchasing/``.

Concurrency (ADR 0003): the PO GET returns a strong ``ETag`` and honours
``If-None-Match`` (304). Both PO mutations — ``PATCH`` on the PO detail and
``POST`` on delivery receipts — require ``If-Match``: missing → 428 here,
mismatch → 412 via the ``PreconditionFailedError`` handler in
``apps/core/envelope.py``. The delivery-receipt endpoint carries the PO id in
the request BODY rather than the URL; the frontend concurrency lib special-cases
that so the right ETag still travels
(``frontend/src/lib/concurrency/interceptors.ts``).
``ResourceVersionMiddleware`` mirrors ``"po:...`` ETags into
``X-Resource-Version``.

Every endpoint requires authenticated staff; the purchasing surface has no
office-staff gate.

No endpoint below writes to Xero; PO push/delete belongs to the separate
``/api/xero/`` integration surface. The receipt service deliberately does not
push, and ``supplier_has_xero_id`` is only a local read.

Integration wiring (config/api.py): ``api.add_router("/", router)`` — the paths
below carry their own ``/purchasing/`` prefix.
"""

import logging
from uuid import UUID

from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import FileResponse, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404
from ninja import Query, Router
from ninja.errors import HttpError
from ninja.responses import Status

from apps.accounts.models import Staff
from apps.core.auth import CookieJWTAuth
from apps.core.etag import if_none_match_satisfied
from apps.job.models import Job
from apps.job.services import job_service
from apps.purchasing.models import PurchaseOrder, Stock
from apps.purchasing.schemas import (
    AllJobsResponse,
    AllocationDeleteRequest,
    AllocationDeleteResponse,
    AllocationDetailsResponse,
    DeliveryReceiptRequest,
    DeliveryReceiptResponse,
    PatchedStockItemRequest,
    ProductMappingListResponse,
    ProductMappingValidateRequest,
    ProductMappingValidateResponse,
    PurchaseOrderAllocationsResponse,
    PurchaseOrderCreateRequest,
    PurchaseOrderCreateResponse,
    PurchaseOrderDetail,
    PurchaseOrderEmailRequest,
    PurchaseOrderEmailResponse,
    PurchaseOrderEventCreateRequest,
    PurchaseOrderEventCreateResponse,
    PurchaseOrderEventsResponse,
    PurchaseOrderLastNumberResponse,
    PurchaseOrderLineCreateRequest,
    PurchaseOrderLineUpdateRequest,
    PurchaseOrderList,
    PurchaseOrderListQuery,
    PurchaseOrderUpdateRequest,
    PurchaseOrderUpdateResponse,
    PurchasingJob,
    StockConsumeRequest,
    StockConsumeResponse,
    StockItem,
    StockItemRequest,
    StockSearchQuery,
    StockSearchResponse,
    SupplierPriceStatusResponse,
    SupplierSearchQuery,
    SupplierSearchResponse,
)
from apps.purchasing.services import (
    allocation_service,
    delivery_receipt_service,
    purchase_order_service,
    stock_search_service,
    stock_service,
    supplier_pricing_service,
    supplier_search_service,
)
from apps.purchasing.services.purchase_order_email_service import create_purchase_order_email
from apps.purchasing.services.purchase_order_pdf_service import create_purchase_order_pdf
from apps.purchasing.services.purchase_order_service import (
    PurchaseOrderCreateData,
    PurchaseOrderLineWriteData,
    PurchaseOrderUpdateData,
)
from apps.purchasing.services.stock_service import StockWriteData
from apps.quoting.models import ProductParsingMapping

logger = logging.getLogger(__name__)

router = Router()

auth = CookieJWTAuth()

# Job statuses a purchase-order line may be costed against.
PURCHASING_JOB_STATUSES = (
    "quoting",
    "accepted_quote",
    "awaiting_materials",
    "awaiting_staff",
    "awaiting_site_availability",
    "in_progress",
    "on_hold",
    "recently_completed",
)


# ── Shared helpers ───────────────────────────────────────────────────────


def _staff(request: HttpRequest) -> Staff:
    """Narrow the authenticated user to a real Staff row (ADR 0028)."""
    auth_user: object = getattr(request, "auth", None)
    user = auth_user if isinstance(auth_user, Staff) else request.user
    if not isinstance(user, Staff):
        raise HttpError(401, "Authentication credentials were not provided.")
    return user


def _require_if_match(request: HttpRequest) -> str:
    """Return the If-Match header or answer 428 Precondition Required."""
    if_match = request.headers.get("If-Match")
    if not if_match:
        raise HttpError(428, "Missing If-Match header (precondition required)")
    return if_match


def _get_po_or_404(po_id: UUID) -> PurchaseOrder:
    # Fetch POs of any status so a deleted PO
    # stays viewable, matching the list endpoint.
    return get_object_or_404(
        PurchaseOrder.objects.select_related("supplier", "created_by", "pickup_address"),
        id=po_id,
    )


def _validation_message(exc: DjangoValidationError) -> str:
    return "; ".join(exc.messages)


# ── Job pickers ──────────────────────────────────────────────────────────


@router.get(
    "/purchasing/all-jobs/",
    auth=auth,
    operation_id="purchasing_all_jobs_retrieve",
    response=AllJobsResponse,
    summary="List all jobs with the stock-holding flag",
    tags=["purchasing"],
)
def purchasing_all_jobs_retrieve(request: HttpRequest) -> dict[str, object]:
    """All non-archived jobs, flagging which one holds general stock."""
    stock_holding_job = Stock.get_stock_holding_job()
    jobs = Job.objects.exclude(status="archived").select_related("company").order_by("job_number")
    return {
        "success": True,
        "jobs": [
            {
                "id": job.id,
                "job_number": job.job_number,
                "name": job.name,
                "company_name": job.company.name if job.company else "No Company",
                "status": job.status,
                "is_stock_holding": job.id == stock_holding_job.id,
                "job_display_name": f"{job.job_number} - {job.name}",
            }
            for job in jobs
        ],
        "stock_holding_job_id": str(stock_holding_job.id),
    }


@router.get(
    "/purchasing/jobs/",
    auth=auth,
    operation_id="purchasing_jobs_retrieve",
    response=list[PurchasingJob],
    summary="List jobs that can carry purchasing costs",
    tags=["purchasing"],
)
def purchasing_jobs_retrieve(request: HttpRequest) -> list[dict[str, object]]:
    """Jobs in a state that can accept material costs, with their actual cost set."""
    jobs = (
        Job.objects.filter(status__in=PURCHASING_JOB_STATUSES)
        .select_related("company", "latest_actual")
        .order_by("job_number")
    )
    return [
        {
            "id": str(job.id),
            "job_number": job.job_number,
            "name": job.name,
            "company_name": job.company.name if job.company else "No Company",
            "status": job.status,
            "cost_set_id": str(job.latest_actual.id),
            "job_display_name": f"{job.job_number} - {job.name}",
        }
        for job in jobs
        if job.latest_actual is not None
    ]


# ── Purchase orders ──────────────────────────────────────────────────────


@router.get(
    "/purchasing/purchase-orders/",
    auth=auth,
    operation_id="listPurchaseOrders",
    response=list[PurchaseOrderList],
    summary="List purchase orders",
    tags=["purchasing"],
)
def list_purchase_orders(
    request: HttpRequest, params: Query[PurchaseOrderListQuery]
) -> list[purchase_order_service.PurchaseOrderListData]:
    """List POs, optionally filtered to a comma-separated set of statuses."""
    return purchase_order_service.list_purchase_orders(params.status)


@router.post(
    "/purchasing/purchase-orders/",
    auth=auth,
    operation_id="createPurchaseOrder",
    response={201: PurchaseOrderCreateResponse},
    summary="Create a purchase order",
    tags=["purchasing"],
)
def create_purchase_order(
    request: HttpRequest, payload: PurchaseOrderCreateRequest, response: HttpResponse
) -> Status[dict[str, object]]:
    """Create a PO and its lines; the model assigns the next PO number."""
    data: PurchaseOrderCreateData = {
        "supplier_id": payload.supplier_id,
        "pickup_address_id": payload.pickup_address_id,
        "reference": payload.reference,
        "order_date": payload.order_date,
        "expected_delivery": payload.expected_delivery,
        "lines": [_line_write_data(line) for line in payload.lines],
    }
    try:
        po = purchase_order_service.create_purchase_order(data, created_by=_staff(request))
    except DjangoValidationError as exc:
        raise HttpError(400, _validation_message(exc)) from exc
    response.headers["ETag"] = purchase_order_service.purchase_order_etag(po)
    return Status(201, {"id": po.id, "po_number": po.po_number})


@router.get(
    "/purchasing/purchase-orders/last-number/",
    auth=auth,
    operation_id="getLastPurchaseOrderNumber",
    response=PurchaseOrderLastNumberResponse,
    summary="Fetch the most recent purchase order number",
    tags=["purchasing"],
)
def get_last_purchase_order_number(request: HttpRequest) -> dict[str, object]:
    """Return the highest PO number issued under the configured prefix."""
    return {"last_po_number": purchase_order_service.get_last_purchase_order_number()}


@router.get(
    "/purchasing/purchase-orders/{uuid:po_id}/",
    auth=auth,
    operation_id="retrievePurchaseOrder",
    response={200: PurchaseOrderDetail, 304: None},
    summary="Fetch a purchase order with its lines",
    tags=["purchasing"],
)
def retrieve_purchase_order(
    request: HttpRequest, po_id: UUID, response: HttpResponse
) -> Status[None] | dict[str, object]:
    """Fetch PO details (conditional GET via If-None-Match, ADR 0003)."""
    po = _get_po_or_404(po_id)
    etag = purchase_order_service.purchase_order_etag(po)
    response.headers["ETag"] = etag
    if_none_match = request.headers.get("If-None-Match")
    if if_none_match and if_none_match_satisfied(if_none_match, etag):
        return Status(304, None)
    return purchase_order_service.purchase_order_detail_data(po)


def _line_write_data(  # noqa: C901 -- one branch per PO-line field; a loop would need dynamic keys
    line: PurchaseOrderLineCreateRequest | PurchaseOrderLineUpdateRequest,
) -> PurchaseOrderLineWriteData:
    """Collect only the line fields the caller actually sent.

    Partial updates write only what arrived; schema defaults must not reset an
    omitted quantity or price flag.
    """
    provided = line.model_fields_set
    data: PurchaseOrderLineWriteData = {}
    if isinstance(line, PurchaseOrderLineUpdateRequest):
        data["id"] = line.id
    if "job_id" in provided:
        data["job_id"] = line.job_id
    if "description" in provided:
        data["description"] = line.description
    if "quantity" in provided:
        data["quantity"] = line.quantity
    if "unit_cost" in provided:
        data["unit_cost"] = line.unit_cost
    if "price_tbc" in provided:
        data["price_tbc"] = line.price_tbc
    if "item_code" in provided:
        data["item_code"] = line.item_code
    if "metal_type" in provided:
        data["metal_type"] = line.metal_type
    if "alloy" in provided:
        data["alloy"] = line.alloy
    if "specifics" in provided:
        data["specifics"] = line.specifics
    if "location" in provided:
        data["location"] = line.location
    if "dimensions" in provided:
        data["dimensions"] = line.dimensions
    return data


@router.patch(
    "/purchasing/purchase-orders/{uuid:po_id}/",
    auth=auth,
    operation_id="purchasing_purchase_orders_partial_update",
    response=PurchaseOrderUpdateResponse,
    summary="Update a purchase order",
    tags=["purchasing"],
)
def purchasing_purchase_orders_partial_update(
    request: HttpRequest,
    po_id: UUID,
    payload: PurchaseOrderUpdateRequest,
    response: HttpResponse,
) -> dict[str, object]:
    """Update a PO under optimistic concurrency (If-Match required, ADR 0003)."""
    if_match = _require_if_match(request)
    provided = payload.model_fields_set
    data: PurchaseOrderUpdateData = {}
    if "supplier_id" in provided:
        data["supplier_id"] = payload.supplier_id
    if "pickup_address_id" in provided:
        data["pickup_address_id"] = payload.pickup_address_id
    if "reference" in provided:
        data["reference"] = payload.reference
    if "expected_delivery" in provided:
        data["expected_delivery"] = payload.expected_delivery
    if "status" in provided:
        data["status"] = payload.status
    if "lines_to_delete" in provided:
        data["lines_to_delete"] = payload.lines_to_delete
    if "lines" in provided:
        data["lines"] = [_line_write_data(line) for line in payload.lines]

    try:
        po = purchase_order_service.update_purchase_order(
            po_id, data, staff=_staff(request), if_match=if_match
        )
    except DjangoValidationError as exc:
        raise HttpError(400, _validation_message(exc)) from exc
    except ValueError as exc:
        # Moving a PO to "fully received" auto-allocates every line, which
        # refuses a line whose price is still TBC. That is a bad request, not
        # a crash. Stock and job allocations use the same 400 contract.
        raise HttpError(400, str(exc)) from exc
    response.headers["ETag"] = purchase_order_service.purchase_order_etag(po)
    return {"id": po.id, "status": po.status}


@router.get(
    "/purchasing/purchase-orders/{uuid:po_id}/pdf/",
    auth=auth,
    operation_id="getPurchaseOrderPDF",
    summary="Download the purchase order PDF",
    tags=["purchasing"],
)
def get_purchase_order_pdf(request: HttpRequest, po_id: UUID) -> FileResponse:
    """Generate and stream the PO PDF as an attachment."""
    po = _get_po_or_404(po_id)
    return FileResponse(
        create_purchase_order_pdf(po),
        content_type="application/pdf",
        as_attachment=True,
        filename=f"Purchase_Order_{po.po_number}.pdf",
    )


@router.post(
    "/purchasing/purchase-orders/{uuid:po_id}/email/",
    auth=auth,
    operation_id="getPurchaseOrderEmail",
    response=PurchaseOrderEmailResponse,
    summary="Compose the supplier email for a purchase order",
    tags=["purchasing"],
)
def get_purchase_order_email(
    request: HttpRequest, po_id: UUID, payload: PurchaseOrderEmailRequest
) -> dict[str, object]:
    """Build the mailto payload, applying any recipient/message overrides."""
    po = _get_po_or_404(po_id)
    try:
        email = create_purchase_order_email(
            po, recipient_email=payload.recipient_email, message=payload.message
        )
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc
    return {
        "success": True,
        "email_subject": email.subject,
        "email_body": email.body,
        "mailto_url": email.mailto_url,
        "message": "Email data generated successfully",
    }


@router.get(
    "/purchasing/purchase-orders/{uuid:po_id}/events/",
    auth=auth,
    operation_id="listPurchaseOrderEvents",
    response=PurchaseOrderEventsResponse,
    summary="List a purchase order's events",
    tags=["Purchase Orders"],
)
def list_purchase_order_events(request: HttpRequest, po_id: UUID) -> dict[str, object]:
    """List every note recorded against the PO, newest first."""
    po = _get_po_or_404(po_id)
    return {"events": purchase_order_service.list_purchase_order_events(po)}


@router.post(
    "/purchasing/purchase-orders/{uuid:po_id}/events/",
    auth=auth,
    operation_id="createPurchaseOrderEvent",
    response={201: PurchaseOrderEventCreateResponse},
    summary="Add a note to a purchase order",
    tags=["Purchase Orders"],
)
def create_purchase_order_event(
    request: HttpRequest, po_id: UUID, payload: PurchaseOrderEventCreateRequest
) -> Status[dict[str, object]]:
    """Record a manual note/comment on the PO."""
    po = _get_po_or_404(po_id)
    event = purchase_order_service.create_purchase_order_event(
        po, payload.description, _staff(request)
    )
    return Status(
        201,
        {"success": True, "event": purchase_order_service.purchase_order_event_data(event)},
    )


# ── Allocations ──────────────────────────────────────────────────────────


@router.get(
    "/purchasing/purchase-orders/{uuid:po_id}/allocations/",
    auth=auth,
    operation_id="purchasing_purchase_orders_allocations_retrieve",
    response=PurchaseOrderAllocationsResponse,
    summary="List existing allocations for a purchase order",
    tags=["purchasing"],
)
def purchasing_purchase_orders_allocations_retrieve(
    request: HttpRequest, po_id: UUID
) -> dict[str, object]:
    """Group this PO's stock and job allocations by PO line."""
    po = _get_po_or_404(po_id)
    return {"po_id": po.id, "allocations": allocation_service.list_allocations(po)}


@router.get(
    "/purchasing/purchase-orders/{uuid:po_id}/allocations/{allocation_type}/"
    "{uuid:allocation_id}/details/",
    auth=auth,
    operation_id="getAllocationDetails",
    response=AllocationDetailsResponse,
    summary="Describe one allocation before deleting it",
    tags=["purchasing"],
)
def get_allocation_details(
    request: HttpRequest, po_id: UUID, allocation_type: str, allocation_id: UUID
) -> dict[str, object]:
    """Return the allocation's quantity, job and whether it can still be deleted."""
    valid_types = (allocation_service.STOCK_ALLOCATION, allocation_service.JOB_ALLOCATION)
    if allocation_type not in valid_types:
        raise HttpError(400, f"Invalid allocation type: {allocation_type}")
    try:
        return allocation_service.get_allocation_details(
            po_id=po_id,
            allocation_type=allocation_type,
            allocation_id=allocation_id,
        )
    except allocation_service.AllocationDeletionError as exc:
        raise HttpError(404, str(exc)) from exc


@router.post(
    "/purchasing/purchase-orders/{uuid:po_id}/lines/{uuid:line_id}/allocations/delete/",
    auth=auth,
    operation_id="deleteAllocation",
    response=AllocationDeleteResponse,
    summary="Delete one allocation from a purchase order line",
    tags=["purchasing"],
)
def delete_allocation(
    request: HttpRequest, po_id: UUID, line_id: UUID, payload: AllocationDeleteRequest
) -> dict[str, object]:
    """Delete a Stock or CostLine allocation and recompute the PO status."""
    try:
        result = allocation_service.delete_allocation(
            po_id=po_id,
            allocation_type=payload.allocation_type,
            allocation_id=payload.allocation_id,
        )
    except allocation_service.AllocationDeletionError as exc:
        raise HttpError(400, str(exc)) from exc
    return {
        "success": result.success,
        "message": result.message,
        "deleted_quantity": result.deleted_quantity,
        "description": result.description,
        "job_name": result.job_name,
        "updated_received_quantity": result.updated_received_quantity,
    }


# ── Delivery receipts ────────────────────────────────────────────────────


@router.post(
    "/purchasing/delivery-receipts/",
    auth=auth,
    operation_id="purchasing_delivery_receipts_create",
    response=DeliveryReceiptResponse,
    summary="Process a delivery receipt",
    tags=["purchasing"],
)
def purchasing_delivery_receipts_create(
    request: HttpRequest, payload: DeliveryReceiptRequest, response: HttpResponse
) -> dict[str, object]:
    """Post received quantities against a PO (If-Match required, ADR 0003).

    The PO id is in the body, not the URL — see the module docstring.
    """
    if_match = _require_if_match(request)
    line_allocations = {
        line_id: delivery_receipt_service.ReceiptLineRequest(
            total_received=line.total_received,
            allocations=[
                delivery_receipt_service.ReceiptAllocationRequest(
                    job_id=alloc.job_id,
                    quantity=alloc.quantity,
                    retail_rate=alloc.retail_rate,
                    metadata=alloc.metadata,
                )
                for alloc in line.allocations
            ],
        )
        for line_id, line in payload.allocations.items()
    }
    try:
        po = delivery_receipt_service.process_delivery_receipt(
            payload.purchase_order_id,
            line_allocations,
            _staff(request),
            if_match=if_match,
        )
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc
    response.headers["ETag"] = purchase_order_service.purchase_order_etag(po)
    return {"success": True}


# ── Stock ────────────────────────────────────────────────────────────────


@router.get(
    "/purchasing/stock/",
    auth=auth,
    operation_id="purchasing_stock_list",
    response=list[StockItem],
    summary="List active stock",
    tags=["purchasing"],
)
def purchasing_stock_list(request: HttpRequest) -> list[stock_service.StockItemData]:
    """List every active stock item, newest first."""
    return [
        stock_service.stock_item_data(stock)
        for stock in Stock.objects.filter(is_active=True).order_by("-date")
    ]


@router.post(
    "/purchasing/stock/",
    auth=auth,
    operation_id="purchasing_stock_create",
    response={201: StockItem},
    summary="Create a stock item",
    tags=["purchasing"],
)
def purchasing_stock_create(
    request: HttpRequest, payload: StockItemRequest
) -> Status[stock_service.StockItemData]:
    """Create a stock item on the stock-holding job."""
    stock = stock_service.create_stock(_stock_write_data(payload))
    return Status(201, stock_service.stock_item_data(stock))


@router.get(
    "/purchasing/stock/search/",
    auth=auth,
    operation_id="purchasing_stock_search_retrieve",
    response=StockSearchResponse,
    summary="Search stock",
    tags=["Stock"],
)
def purchasing_stock_search_retrieve(
    request: HttpRequest, params: Query[StockSearchQuery]
) -> stock_search_service.StockSearchPage:
    """Paginated stock listing; queries under 3 characters list everything."""
    query = params.q.strip()
    try:
        return stock_search_service.list_stock(
            query=query if len(query) >= 3 else None,
            page=max(1, params.page),
            page_size=params.page_size,
            sort_by=params.sort_by,
            sort_dir=params.sort_dir,
        )
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc


@router.get(
    "/purchasing/stock/{uuid:id}/",
    auth=auth,
    operation_id="purchasing_stock_retrieve",
    response=StockItem,
    summary="Fetch a stock item",
    tags=["purchasing"],
)
def purchasing_stock_retrieve(request: HttpRequest, id: UUID) -> stock_service.StockItemData:
    """Fetch one active stock item."""
    return stock_service.stock_item_data(_get_stock_or_404(id))


@router.put(
    "/purchasing/stock/{uuid:id}/",
    auth=auth,
    operation_id="purchasing_stock_update",
    response=StockItem,
    summary="Replace a stock item",
    tags=["purchasing"],
)
def purchasing_stock_update(
    request: HttpRequest, id: UUID, payload: StockItemRequest
) -> stock_service.StockItemData:
    """Full update of a stock item."""
    stock = stock_service.update_stock(_get_stock_or_404(id), _stock_write_data(payload))
    return stock_service.stock_item_data(stock)


@router.patch(
    "/purchasing/stock/{uuid:id}/",
    auth=auth,
    operation_id="purchasing_stock_partial_update",
    response=StockItem,
    summary="Update a stock item",
    tags=["purchasing"],
)
def purchasing_stock_partial_update(
    request: HttpRequest, id: UUID, payload: PatchedStockItemRequest
) -> stock_service.StockItemData:
    """Partial update of a stock item (only the provided fields are written)."""
    stock = stock_service.update_stock(_get_stock_or_404(id), _patched_stock_write_data(payload))
    return stock_service.stock_item_data(stock)


@router.delete(
    "/purchasing/stock/{uuid:id}/",
    auth=auth,
    operation_id="purchasing_stock_destroy",
    response={204: None},
    summary="Deactivate a stock item",
    tags=["purchasing"],
)
def purchasing_stock_destroy(request: HttpRequest, id: UUID) -> Status[None]:
    """Soft-delete a stock item by setting ``is_active=False``."""
    stock_service.deactivate_stock(_get_stock_or_404(id))
    return Status(204, None)


@router.post(
    "/purchasing/stock/{uuid:id}/consume/",
    auth=auth,
    operation_id="consumeStock",
    response=StockConsumeResponse,
    summary="Consume stock for a job",
    tags=["purchasing"],
)
def consume_stock(
    request: HttpRequest, id: UUID, payload: StockConsumeRequest
) -> dict[str, object]:
    """Take quantity off a stock item and book it as a material cost line."""
    stock = _get_stock_or_404(id)
    job = get_object_or_404(Job, id=payload.job_id)
    try:
        line = stock_service.consume_stock(
            item=stock,
            job=job,
            qty=payload.quantity,
            user=_staff(request),
            unit_cost=payload.unit_cost,
            unit_rev=payload.unit_rev,
        )
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc
    return {
        "success": True,
        "message": "Stock consumed successfully",
        "remaining_quantity": stock.quantity,
        "line": job_service.cost_line_data(line),
    }


def _get_stock_or_404(stock_id: UUID) -> Stock:
    # The public queryset is active-only, so an inactive row is a 404.
    return get_object_or_404(Stock, id=stock_id, is_active=True)


def _stock_write_data(payload: StockItemRequest) -> StockWriteData:
    """Collect the full stock write payload (``date`` defaults on create)."""
    data: StockWriteData = {
        "description": payload.description,
        "quantity": payload.quantity,
        "unit_cost": payload.unit_cost,
        "source": payload.source,
        "item_code": payload.item_code,
        "unit_revenue": payload.unit_revenue,
        "location": payload.location,
        "metal_type": payload.metal_type,
        "alloy": payload.alloy,
        "specifics": payload.specifics,
        "is_active": payload.is_active,
    }
    if payload.date is not None:
        data["date"] = payload.date
    return data


def _patched_stock_write_data(  # noqa: C901 -- one branch per Stock field; a loop would need dynamic keys
    payload: PatchedStockItemRequest,
) -> StockWriteData:
    """Collect only the stock fields the caller actually sent."""
    provided = payload.model_fields_set
    data: StockWriteData = {}
    # NOT NULL columns: the schema rejects null outright, so presence is the
    # only question left here.
    if "description" in provided:
        data["description"] = payload.description
    if "quantity" in provided:
        data["quantity"] = payload.quantity
    if "unit_cost" in provided:
        data["unit_cost"] = payload.unit_cost
    if "source" in provided:
        data["source"] = payload.source
    if "is_active" in provided:
        data["is_active"] = payload.is_active
    # Nullable fields: an explicit null (or blank) clears them.
    if "item_code" in provided:
        data["item_code"] = payload.item_code
    if "unit_revenue" in provided:
        data["unit_revenue"] = payload.unit_revenue
    if "date" in provided:
        data["date"] = payload.date
    if "location" in provided:
        data["location"] = payload.location
    if "metal_type" in provided:
        data["metal_type"] = payload.metal_type
    if "alloy" in provided:
        data["alloy"] = payload.alloy
    if "specifics" in provided:
        data["specifics"] = payload.specifics
    return data


# ── Supplier lookup and pricing ──────────────────────────────────────────


@router.get(
    "/purchasing/suppliers/search/",
    auth=auth,
    operation_id="purchasing_suppliers_search_retrieve",
    response=SupplierSearchResponse,
    summary="Search purchase-order suppliers",
    tags=["Purchasing"],
)
def purchasing_suppliers_search_retrieve(
    request: HttpRequest, params: Query[SupplierSearchQuery]
) -> supplier_search_service.SupplierSearchPage:
    """Rank supplier candidates by name/alias match and recent purchases."""
    query = params.q.strip()
    try:
        return supplier_search_service.list_suppliers(
            query=query or None, page=params.page, page_size=params.page_size
        )
    except ValueError as exc:
        raise HttpError(400, str(exc)) from exc


@router.get(
    "/purchasing/supplier-price-status/",
    auth=auth,
    operation_id="getSupplierPriceStatus",
    response=SupplierPriceStatusResponse,
    summary="Report the latest price upload per supplier",
    tags=["purchasing"],
)
def get_supplier_price_status(request: HttpRequest) -> dict[str, object]:
    """Read-only status of each supplier's most recent price list."""
    items = supplier_pricing_service.supplier_price_status()
    return {"items": items, "total_count": len(items)}


@router.get(
    "/purchasing/product-mappings/",
    auth=auth,
    operation_id="listProductMappings",
    response=ProductMappingListResponse,
    summary="List product parsing mappings",
    tags=["Product Mapping"],
)
def list_product_mappings(request: HttpRequest) -> dict[str, object]:
    """List mappings with unvalidated ones first, plus review counts."""
    mappings, validated_count, unvalidated_count = supplier_pricing_service.list_product_mappings()
    return {
        "items": mappings,
        "total_count": len(mappings),
        "validated_count": validated_count,
        "unvalidated_count": unvalidated_count,
    }


@router.post(
    "/purchasing/product-mappings/{uuid:mapping_id}/validate/",
    auth=auth,
    operation_id="validateProductMapping",
    response=ProductMappingValidateResponse,
    summary="Validate a product parsing mapping",
    tags=["Product Mapping"],
)
def validate_product_mapping(
    request: HttpRequest, mapping_id: UUID, payload: ProductMappingValidateRequest
) -> dict[str, object]:
    """Sign off a mapping and back-flow its values onto the matching products."""
    mapping = get_object_or_404(ProductParsingMapping, id=mapping_id)
    provided = payload.model_fields_set
    data: supplier_pricing_service.ProductMappingValidateData = {}
    if "mapped_item_code" in provided:
        data["mapped_item_code"] = payload.mapped_item_code
    if "mapped_description" in provided:
        data["mapped_description"] = payload.mapped_description
    if "mapped_metal_type" in provided:
        data["mapped_metal_type"] = payload.mapped_metal_type
    if "mapped_alloy" in provided:
        data["mapped_alloy"] = payload.mapped_alloy
    if "mapped_specifics" in provided:
        data["mapped_specifics"] = payload.mapped_specifics
    if "mapped_dimensions" in provided:
        data["mapped_dimensions"] = payload.mapped_dimensions
    if "mapped_unit_cost" in provided:
        data["mapped_unit_cost"] = payload.mapped_unit_cost
    if "mapped_price_unit" in provided:
        data["mapped_price_unit"] = payload.mapped_price_unit
    if "validation_notes" in provided:
        data["validation_notes"] = payload.validation_notes
    updated = supplier_pricing_service.validate_product_mapping(mapping, data, _staff(request))
    return {
        "success": True,
        "message": f"Mapping validated successfully. Updated {updated} related products.",
        "updated_products_count": updated,
    }
