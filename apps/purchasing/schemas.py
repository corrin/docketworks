"""Pydantic schemas for the purchasing router (wire shapes match frontend/schema.yml).

Success bodies mirror v1's DRF serializers (``apps/purchasing/serializers.py``);
the service layer builds matching TypedDict data. Error bodies use the v2
envelope (ADR 0013).

The PO/PO-line/Stock field lists live here — v1 kept them as
``PURCHASEORDER_API_FIELDS``-style class attributes on the models AND repeated
them across serializers; v2 has one home per wire shape (ADR 0039).
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
    """Query params for listPurchaseOrders (v1 ``?status=a,b``)."""

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
    """v1 PurchasingErrorResponseSerializer."""

    error: str
    details: str | None = None


# ── Jobs in purchasing contexts ──────────────────────────────────────────


class JobForPurchasing(Schema):
    """v1 JobForPurchasingSerializer."""

    id: UUID
    job_number: int
    name: str
    company_name: str
    status: str
    is_stock_holding: bool
    job_display_name: str


class AllJobsResponse(Schema):
    """v1 AllJobsResponseSerializer."""

    success: bool
    jobs: list[JobForPurchasing]
    stock_holding_job_id: str


class PurchasingJob(Schema):
    """One row of purchasing_jobs_retrieve.

    v1 declared ``PurchasingJobsResponseSerializer`` for this endpoint but the
    view returned a bare list of these dicts; the list is the real contract.
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
    """v1 PurchaseOrderJobSerializer (job summary inside a PO list row)."""

    job_number: str
    name: str
    company: str


class PurchaseOrderList(Schema):
    """v1 PurchaseOrderListSerializer."""

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
    """v1 PurchaseOrderLineSerializer (PURCHASEORDERLINE_API_FIELDS + job info)."""

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
    """v1 PurchaseOrderDetailSerializer."""

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
    """v1 PurchaseOrderLineCreateSerializer."""

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
    """v1 PurchaseOrderLineUpdateSerializer (create fields plus the row id)."""

    id: UUID | None = None


class PurchaseOrderCreateRequest(Schema):
    """v1 PurchaseOrderCreateSerializer."""

    supplier_id: UUID | None = None
    pickup_address_id: UUID | None = None
    reference: str | None = None
    order_date: date | None = None
    expected_delivery: date | None = None
    lines: list[PurchaseOrderLineCreateRequest] = []  # noqa: RUF012 -- pydantic copies defaults


class PurchaseOrderCreateResponse(Schema):
    """v1 PurchaseOrderCreateResponseSerializer."""

    id: UUID
    po_number: str


class PurchaseOrderUpdateRequest(Schema):
    """v1 PurchaseOrderUpdateSerializer (the PATCH body)."""

    supplier_id: UUID | None = None
    pickup_address_id: UUID | None = None
    reference: str | None = None
    expected_delivery: date | None = None
    status: str | None = None
    lines_to_delete: list[UUID] | None = None
    lines: list[PurchaseOrderLineUpdateRequest] | None = None


class PurchaseOrderUpdateResponse(Schema):
    """v1 PurchaseOrderUpdateResponseSerializer."""

    id: UUID
    status: str


class PurchaseOrderLastNumberResponse(Schema):
    """v1 PurchaseOrderLastNumberResponseSerializer."""

    last_po_number: str | None


# ── Purchase order events ────────────────────────────────────────────────


class PurchaseOrderEventOut(Schema):
    """v1 PurchaseOrderEventSerializer."""

    id: UUID
    description: str
    timestamp: datetime
    staff: str


class PurchaseOrderEventsResponse(Schema):
    """v1 PurchaseOrderEventsResponseSerializer."""

    events: list[PurchaseOrderEventOut]


class PurchaseOrderEventCreateRequest(Schema):
    """v1 PurchaseOrderEventCreateSerializer."""

    description: str


class PurchaseOrderEventCreateResponse(Schema):
    """v1 PurchaseOrderEventCreateResponseSerializer."""

    success: bool
    event: PurchaseOrderEventOut


# ── Purchase order email ─────────────────────────────────────────────────


class PurchaseOrderEmailRequest(Schema):
    """v1 PurchaseOrderEmailSerializer."""

    recipient_email: str | None = None
    message: str | None = None

    @field_validator("recipient_email")
    @classmethod
    def _validate_recipient_email(cls, value: str | None) -> str | None:
        # v1 declared this as a DRF EmailField, so a typo was a 400 there even
        # though the view only used the value to override the mailto target.
        return clean_optional_email(value)


class PurchaseOrderEmailResponse(Schema):
    """v1 PurchaseOrderEmailResponseSerializer."""

    success: bool
    email_subject: str | None = None
    email_body: str | None = None
    mailto_url: str | None = None
    pdf_url: str | None = None
    message: str | None = None


# ── Delivery receipts ────────────────────────────────────────────────────


class DeliveryReceiptAllocationRequest(Schema):
    """v1 DeliveryReceiptAllocationSerializer."""

    job_id: UUID
    quantity: Decimal
    retail_rate: Decimal | None = None
    metadata: dict[str, str] = {}  # noqa: RUF012 -- pydantic copies defaults


class DeliveryReceiptLineRequest(Schema):
    """v1 DeliveryReceiptLineSerializer."""

    total_received: Decimal
    allocations: list[DeliveryReceiptAllocationRequest]


class DeliveryReceiptRequest(Schema):
    """v1 DeliveryReceiptSerializer.

    The purchase order id travels in the BODY, not the URL — the frontend
    concurrency lib reads it from here to pick the right ``If-Match`` ETag
    (``frontend/src/lib/concurrency/interceptors.ts``).
    """

    purchase_order_id: UUID
    allocations: dict[str, DeliveryReceiptLineRequest]


class DeliveryReceiptResponse(Schema):
    """v1 DeliveryReceiptResponseSerializer."""

    success: bool
    error: str | None = None


# ── Allocations ──────────────────────────────────────────────────────────


class AllocationItem(Schema):
    """v1 AllocationItemSerializer."""

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
    """v1 PurchaseOrderAllocationsResponseSerializer."""

    po_id: UUID
    allocations: dict[str, list[AllocationItem]]


class AllocationDeleteRequest(Schema):
    """v1 AllocationDeleteSerializer."""

    allocation_type: Literal["job", "stock"]
    allocation_id: UUID


class AllocationDeleteResponse(Schema):
    """v1 AllocationDeleteResponseSerializer."""

    success: bool
    message: str
    deleted_quantity: float | None = None
    description: str | None = None
    job_name: str | None = None
    updated_received_quantity: float | None = None


class AllocationDetailsResponse(Schema):
    """v1 AllocationDetailsResponseSerializer."""

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
    """v1 StockItemSerializer (STOCK_API_FIELDS + job_id + times_used)."""

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
    """v1 StockItemSerializer write shape (POST/PUT body).

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
    """v1 StockItemSerializer partial-update shape (PATCH body)."""

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
    """v1 StockConsumeSerializer."""

    job_id: UUID
    quantity: Decimal
    unit_cost: Decimal | None = None
    unit_rev: Decimal | None = None


class StockConsumeResponse(Schema):
    """v1 StockConsumeResponseSerializer (also the cost-line approve body)."""

    success: bool
    message: str | None = None
    remaining_quantity: Decimal | None = None
    line: CostLineOut


class StockSearchResponse(Schema):
    """v1 StockSearchResponseSerializer."""

    results: list[StockItem]
    count: int
    page: int
    page_size: int
    total_pages: int


# ── Supplier lookup ──────────────────────────────────────────────────────


class SupplierSearchResult(Schema):
    """v1 SupplierSearchResultSerializer."""

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
    """v1 SupplierSearchResponseSerializer."""

    results: list[SupplierSearchResult]
    count: int
    page: int
    page_size: int
    total_pages: int


class SupplierPriceStatusItem(Schema):
    """v1 SupplierPriceStatusItemSerializer."""

    supplier_id: UUID
    supplier_name: str
    last_uploaded_at: datetime | None
    file_name: str | None
    total_products: int | None
    changes_last_update: int | None


class SupplierPriceStatusResponse(Schema):
    """v1 SupplierPriceStatusResponseSerializer."""

    items: list[SupplierPriceStatusItem]
    total_count: int


# ── Product parsing mappings ─────────────────────────────────────────────


class ProductMapping(Schema):
    """v1 ProductMappingSerializer."""

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
    """v1 ProductMappingListResponseSerializer."""

    items: list[ProductMapping]
    total_count: int
    validated_count: int
    unvalidated_count: int


class ProductMappingValidateRequest(Schema):
    """v1 ProductMappingValidateSerializer, with ADR 0040 blanks-are-422."""

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
    """v1 ProductMappingValidateResponseSerializer."""

    success: bool
    message: str
    updated_products_count: int | None = None
