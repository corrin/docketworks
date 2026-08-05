"""Pydantic wire contracts for the purchasing router.

The service layer builds matching TypedDict data, and error responses use the
standard envelope from ADR 0013. PO, PO-line, and Stock API field lists live
only here so model and response declarations cannot drift (ADR 0039).
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from ninja import Schema
from pydantic import field_validator

from apps.company.schemas import SupplierPickupAddressOut, clean_optional_email
from apps.core.schemas import NullableText
from apps.job.schemas import CostLineOut

# The one NullableText (ADR 0039/0040) lives in apps/core/schemas — company's
# request schemas need it too, and company cannot import purchasing.

# ── Query params ─────────────────────────────────────────────────────────


class PurchaseOrderListQuery(Schema):
    """Query parameters for purchase-order listing, including CSV statuses."""

    status: str | None = None


class StockSearchQuery(Schema):
    """Query params for purchasing_stock_search_retrieve."""

    q: str = ""
    page: int = 1
    page_size: int = 50
    sort_by: str = "description"
    sort_dir: str = "asc"


class SupplierSearchQuery(Schema):
    """Query params for purchasing_suppliers_search_retrieve."""

    q: str = ""
    page: int = 1
    page_size: int = 50


# ── Errors ───────────────────────────────────────────────────────────────


class PurchasingErrorResponse(Schema):
    """Wire contract for PurchasingErrorResponse."""

    error: str
    details: str | None = None


# ── Jobs in purchasing contexts ──────────────────────────────────────────


class JobForPurchasing(Schema):
    """Wire contract for JobForPurchasing."""

    id: UUID
    job_number: int
    name: str
    company_name: str
    status: str
    is_stock_holding: bool
    job_display_name: str


class AllJobsResponse(Schema):
    """Wire contract for AllJobsResponse."""

    success: bool
    jobs: list[JobForPurchasing]
    stock_holding_job_id: str


class PurchasingJob(Schema):
    """One row of purchasing_jobs_retrieve.

    The endpoint returns a bare list of these rows rather than a containing
    response object.
    """

    id: str
    job_number: int
    name: str
    company_name: str
    status: str
    cost_set_id: str | None
    job_display_name: str


# ── Purchase orders ──────────────────────────────────────────────────────


class PurchaseOrderJob(Schema):
    """Wire contract for PurchaseOrderJob."""

    job_number: str
    name: str
    company: str


class PurchaseOrderList(Schema):
    """Wire contract for PurchaseOrderList."""

    id: UUID
    po_number: str
    status: str
    order_date: date
    supplier: str
    supplier_id: UUID | None
    created_by_id: UUID | None
    created_by_name: str
    jobs: list[PurchaseOrderJob]


class PurchaseOrderLineOut(Schema):
    """Wire contract for PurchaseOrderLineOut."""

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


class PurchaseOrderDetail(Schema):
    """Wire contract for PurchaseOrderDetail."""

    id: UUID
    po_number: str
    reference: str | None
    status: str
    order_date: date
    expected_delivery: date | None
    online_url: str | None
    xero_id: UUID | None
    pickup_address_id: UUID | None
    created_by_id: UUID | None
    supplier: str
    supplier_id: UUID | None
    supplier_has_xero_id: bool
    lines: list[PurchaseOrderLineOut]
    pickup_address: SupplierPickupAddressOut | None
    created_by_name: str


class PurchaseOrderLineCreateRequest(Schema):
    """Wire contract for PurchaseOrderLineCreateRequest."""

    job_id: UUID | None = None
    description: str = ""
    quantity: Decimal = Decimal("0")
    unit_cost: Decimal | None = None
    price_tbc: bool = False
    item_code: NullableText = None
    metal_type: NullableText = None
    alloy: NullableText = None
    specifics: NullableText = None
    location: NullableText = None
    dimensions: NullableText = None


class PurchaseOrderLineUpdateRequest(PurchaseOrderLineCreateRequest):
    """Wire contract for PurchaseOrderLineUpdateRequest."""

    id: UUID | None = None


class PurchaseOrderCreateRequest(Schema):
    """Wire contract for PurchaseOrderCreateRequest."""

    supplier_id: UUID | None = None
    pickup_address_id: UUID | None = None
    reference: str | None = None
    order_date: date | None = None
    expected_delivery: date | None = None
    lines: list[PurchaseOrderLineCreateRequest] = []  # noqa: RUF012 -- pydantic copies defaults


class PurchaseOrderCreateResponse(Schema):
    """Wire contract for PurchaseOrderCreateResponse."""

    id: UUID
    po_number: str


class PurchaseOrderUpdateRequest(Schema):
    """Wire contract for PurchaseOrderUpdateRequest."""

    supplier_id: UUID | None = None
    pickup_address_id: UUID | None = None
    reference: str | None = None
    expected_delivery: date | None = None
    status: str | None = None
    lines_to_delete: list[UUID] | None = None
    lines: list[PurchaseOrderLineUpdateRequest] | None = None


class PurchaseOrderUpdateResponse(Schema):
    """Wire contract for PurchaseOrderUpdateResponse."""

    id: UUID
    status: str


class PurchaseOrderLastNumberResponse(Schema):
    """Wire contract for PurchaseOrderLastNumberResponse."""

    last_po_number: str | None


# ── Purchase order events ────────────────────────────────────────────────


class PurchaseOrderEventOut(Schema):
    """Wire contract for PurchaseOrderEventOut."""

    id: UUID
    description: str
    timestamp: datetime
    staff: str


class PurchaseOrderEventsResponse(Schema):
    """Wire contract for PurchaseOrderEventsResponse."""

    events: list[PurchaseOrderEventOut]


class PurchaseOrderEventCreateRequest(Schema):
    """Wire contract for PurchaseOrderEventCreateRequest."""

    description: str


class PurchaseOrderEventCreateResponse(Schema):
    """Wire contract for PurchaseOrderEventCreateResponse."""

    success: bool
    event: PurchaseOrderEventOut


# ── Purchase order email ─────────────────────────────────────────────────


class PurchaseOrderEmailRequest(Schema):
    """Wire contract for PurchaseOrderEmailRequest."""

    recipient_email: str | None = None
    message: str | None = None

    @field_validator("recipient_email")
    @classmethod
    def _validate_recipient_email(cls, value: str | None) -> str | None:
        # Validate before constructing the mailto target so a typo is a field
        # error rather than an unusable link.
        return clean_optional_email(value)


class PurchaseOrderEmailResponse(Schema):
    """Wire contract for PurchaseOrderEmailResponse."""

    success: bool
    email_subject: str | None = None
    email_body: str | None = None
    mailto_url: str | None = None
    pdf_url: str | None = None
    message: str | None = None


# ── Delivery receipts ────────────────────────────────────────────────────


class DeliveryReceiptAllocationRequest(Schema):
    """Wire contract for DeliveryReceiptAllocationRequest."""

    job_id: UUID
    quantity: Decimal
    retail_rate: Decimal | None = None
    metadata: dict[str, str] = {}  # noqa: RUF012 -- pydantic copies defaults


class DeliveryReceiptLineRequest(Schema):
    """Wire contract for DeliveryReceiptLineRequest."""

    total_received: Decimal
    allocations: list[DeliveryReceiptAllocationRequest]


class DeliveryReceiptRequest(Schema):
    """Delivery-receipt mutation payload.

    The purchase order id travels in the BODY, not the URL — the frontend
    concurrency lib reads it from here to pick the right ``If-Match`` ETag
    (``frontend/src/lib/concurrency/interceptors.ts``).
    """

    purchase_order_id: UUID
    allocations: dict[str, DeliveryReceiptLineRequest]


class DeliveryReceiptResponse(Schema):
    """Wire contract for DeliveryReceiptResponse."""

    success: bool
    error: str | None = None


# ── Allocations ──────────────────────────────────────────────────────────


class AllocationItem(Schema):
    """Wire contract for AllocationItem."""

    type: Literal["stock", "job"]
    job_id: UUID
    job_name: str
    quantity: float
    retail_rate: float = 0
    allocation_date: datetime | None
    description: str
    stock_location: str | None = None
    metal_type: str | None = None
    alloy: str | None = None
    specifics: str | None = None
    allocation_id: UUID | None = None


class PurchaseOrderAllocationsResponse(Schema):
    """Wire contract for PurchaseOrderAllocationsResponse."""

    po_id: UUID
    allocations: dict[str, list[AllocationItem]]


class AllocationDeleteRequest(Schema):
    """Wire contract for AllocationDeleteRequest."""

    allocation_type: Literal["job", "stock"]
    allocation_id: UUID


class AllocationDeleteResponse(Schema):
    """Wire contract for AllocationDeleteResponse."""

    success: bool
    message: str
    deleted_quantity: float | None = None
    description: str | None = None
    job_name: str | None = None
    updated_received_quantity: float | None = None


class AllocationDetailsResponse(Schema):
    """Wire contract for AllocationDetailsResponse."""

    type: Literal["stock", "job"]
    id: UUID
    description: str
    quantity: float
    job_name: str
    can_delete: bool
    consumed_by_jobs: int | None = None
    location: str | None = None
    unit_cost: float | None = None
    unit_revenue: float | None = None


# ── Stock ────────────────────────────────────────────────────────────────


class StockItem(Schema):
    """Wire contract for StockItem."""

    id: UUID
    item_code: str | None
    description: str
    quantity: Decimal
    unit_cost: Decimal
    unit_revenue: Decimal | None
    date: datetime
    source: str
    location: str | None
    metal_type: str | None
    alloy: str | None
    specifics: str | None
    is_active: bool
    job_id: UUID | None
    times_used: int


class StockItemRequest(Schema):
    """Stock-item create and full-update payload.

    The nullable text fields are ``NullableText`` (ADR 0040): ``""`` is a
    validation 422 before the ``*_not_blank`` check constraints ever see it,
    and ``null`` is how a client leaves one unset.
    """

    description: str
    quantity: Decimal
    unit_cost: Decimal
    source: str
    item_code: NullableText = None
    unit_revenue: Decimal | None = None
    date: datetime | None = None
    location: NullableText = None
    metal_type: NullableText = None
    alloy: NullableText = None
    specifics: NullableText = None
    is_active: bool = True


class PatchedStockItemRequest(Schema):
    """Wire contract for PatchedStockItemRequest."""

    description: str | None = None
    quantity: Decimal | None = None
    unit_cost: Decimal | None = None
    source: str | None = None
    item_code: NullableText = None
    unit_revenue: Decimal | None = None
    date: datetime | None = None
    location: NullableText = None
    metal_type: NullableText = None
    alloy: NullableText = None
    specifics: NullableText = None
    is_active: bool | None = None


class StockConsumeRequest(Schema):
    """Wire contract for StockConsumeRequest."""

    job_id: UUID
    quantity: Decimal
    unit_cost: Decimal | None = None
    unit_rev: Decimal | None = None


class StockConsumeResponse(Schema):
    """Wire contract for StockConsumeResponse."""

    success: bool
    message: str | None = None
    remaining_quantity: Decimal | None = None
    line: CostLineOut


class StockSearchResponse(Schema):
    """Wire contract for StockSearchResponse."""

    results: list[StockItem]
    count: int
    page: int
    page_size: int
    total_pages: int


# ── Supplier lookup ──────────────────────────────────────────────────────


class SupplierSearchResult(Schema):
    """Wire contract for SupplierSearchResult."""

    id: str
    name: str
    email: str
    phone: str
    address: str
    is_account_customer: bool
    is_supplier: bool
    allow_jobs: bool
    xero_contact_id: str
    last_invoice_date: datetime | None
    total_spend: str
    recent_purchase_count: int


class SupplierSearchResponse(Schema):
    """Wire contract for SupplierSearchResponse."""

    results: list[SupplierSearchResult]
    count: int
    page: int
    page_size: int
    total_pages: int


class SupplierPriceStatusItem(Schema):
    """Wire contract for SupplierPriceStatusItem."""

    supplier_id: UUID
    supplier_name: str
    last_uploaded_at: datetime | None
    file_name: str | None
    total_products: int | None
    changes_last_update: int | None


class SupplierPriceStatusResponse(Schema):
    """Wire contract for SupplierPriceStatusResponse."""

    items: list[SupplierPriceStatusItem]
    total_count: int


# ── Product parsing mappings ─────────────────────────────────────────────


class ProductMapping(Schema):
    """Wire contract for ProductMapping."""

    id: UUID
    input_hash: str
    input_data: dict[str, object]
    derived_key: str | None
    mapped_item_code: str | None
    mapped_description: str | None
    mapped_metal_type: str | None
    mapped_alloy: str | None
    mapped_specifics: str | None
    mapped_dimensions: str | None
    mapped_unit_cost: Decimal | None
    mapped_price_unit: str | None
    parser_version: str | None
    parser_confidence: Decimal | None
    is_validated: bool
    validated_at: datetime | None
    validation_notes: str | None
    item_code_is_in_xero: bool
    created_at: datetime


class ProductMappingListResponse(Schema):
    """Wire contract for ProductMappingListResponse."""

    items: list[ProductMapping]
    total_count: int
    validated_count: int
    unvalidated_count: int


class ProductMappingValidateRequest(Schema):
    """Wire contract for ProductMappingValidateRequest."""

    mapped_item_code: NullableText = None
    mapped_description: NullableText = None
    mapped_metal_type: NullableText = None
    mapped_alloy: NullableText = None
    mapped_specifics: NullableText = None
    mapped_dimensions: NullableText = None
    mapped_unit_cost: Decimal | None = None
    mapped_price_unit: NullableText = None
    validation_notes: NullableText = None


class ProductMappingValidateResponse(Schema):
    """Wire contract for ProductMappingValidateResponse."""

    success: bool
    message: str
    updated_products_count: int | None = None
