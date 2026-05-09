from decimal import Decimal

from rest_framework import serializers

from apps.client.serializers import SupplierPickupAddressSerializer
from apps.job.models import Job
from apps.job.serializers.costing_serializer import CostLineSerializer
from apps.purchasing.models import (
    PurchaseOrder,
    PurchaseOrderEvent,
    PurchaseOrderLine,
    Stock,
)


class SupplierPriceStatusItemSerializer(serializers.Serializer):
    """Single supplier price status row."""

    supplier_id = serializers.UUIDField()
    supplier_name = serializers.CharField()
    last_uploaded_at = serializers.DateTimeField(allow_null=True)
    file_name = serializers.CharField(allow_null=True, allow_blank=True)
    total_products = serializers.IntegerField(allow_null=True)
    changes_last_update = serializers.IntegerField(allow_null=True)


class SupplierPriceStatusResponseSerializer(serializers.Serializer):
    """Response containing list of supplier price statuses."""

    items = SupplierPriceStatusItemSerializer(many=True)
    total_count = serializers.IntegerField()


class JobForPurchasingSerializer(serializers.ModelSerializer):
    """Serializer for Job model in purchasing contexts."""

    client_name = serializers.SerializerMethodField()
    is_stock_holding = serializers.SerializerMethodField()
    job_display_name = serializers.SerializerMethodField()

    def get_client_name(self, obj) -> str:
        return obj.client.name if obj.client else "No Client"

    def get_is_stock_holding(self, obj) -> bool:
        # This will be set dynamically in the view
        return getattr(obj, "_is_stock_holding", False)

    def get_job_display_name(self, obj) -> str:
        return f"{obj.job_number} - {obj.name}"

    class Meta:
        model = Job
        fields = [
            "id",
            "job_number",
            "name",
            "client_name",
            "status",
            "is_stock_holding",
            "job_display_name",
        ]


class PurchaseOrderLineSerializer(serializers.ModelSerializer):
    """Serializer for PurchaseOrderLine model."""

    job_id = serializers.UUIDField(source="job.id", read_only=True, allow_null=True)
    job_number = serializers.IntegerField(
        source="job.job_number", read_only=True, allow_null=True
    )
    client_name = serializers.CharField(
        source="job.client.name", read_only=True, allow_null=True
    )
    job_name = serializers.CharField(source="job.name", read_only=True, allow_null=True)

    class Meta:
        model = PurchaseOrderLine
        fields = PurchaseOrderLine.PURCHASEORDERLINE_API_FIELDS + [
            "job_id",
            "job_number",
            "client_name",
            "job_name",
        ]


class PurchaseOrderDetailSerializer(serializers.ModelSerializer):
    """Return purchase order details with related lines."""

    supplier = serializers.SerializerMethodField()
    supplier_id = serializers.SerializerMethodField()
    supplier_has_xero_id = serializers.SerializerMethodField()
    created_by_name = serializers.SerializerMethodField()
    lines = PurchaseOrderLineSerializer(source="po_lines", many=True)
    pickup_address = SupplierPickupAddressSerializer(read_only=True, allow_null=True)

    class Meta:
        model = PurchaseOrder
        fields = (
            PurchaseOrder.PURCHASEORDER_API_FIELDS
            + PurchaseOrder.PURCHASEORDER_API_PROPERTIES
            + ["created_by_name"]
        )

    def get_supplier(self, obj) -> str:
        return obj.supplier.name if obj.supplier else ""

    def get_supplier_id(self, obj) -> str | None:
        return str(obj.supplier.id) if obj.supplier else None

    def get_supplier_has_xero_id(self, obj) -> bool:
        return obj.supplier.xero_contact_id is not None if obj.supplier else False

    def get_created_by_name(self, obj) -> str:
        return obj.created_by.get_display_full_name() if obj.created_by else ""


class AllJobsResponseSerializer(serializers.Serializer):
    """Serializer for AllJobsAPIView response."""

    success = serializers.BooleanField()
    jobs = JobForPurchasingSerializer(many=True)
    stock_holding_job_id = serializers.CharField()


class DeliveryReceiptAllocationSerializer(serializers.Serializer):
    """Serializer for individual allocation within a delivery receipt line."""

    job_id = serializers.UUIDField()
    quantity = serializers.DecimalField(max_digits=10, decimal_places=2)
    retail_rate = serializers.DecimalField(
        max_digits=5,
        decimal_places=2,
        required=False,
        help_text="Custom retail rate percentage (e.g., 20.00 for 20%)",
    )
    metadata = serializers.DictField(
        required=False,
        allow_empty=True,
        help_text="Additional metadata including location, metal_type, alloy, specifics",
    )


class DeliveryReceiptLineSerializer(serializers.Serializer):
    """Serializer for delivery receipt line allocation data."""

    total_received = serializers.DecimalField(max_digits=10, decimal_places=2)
    allocations = DeliveryReceiptAllocationSerializer(many=True)


class DeliveryReceiptSerializer(serializers.Serializer):
    """Serializer for delivery receipt request data."""

    purchase_order_id = serializers.UUIDField()
    allocations = serializers.DictField(
        child=DeliveryReceiptLineSerializer(),
        help_text="Dictionary where keys are PurchaseOrderLine IDs and values are allocation data",
    )


class DeliveryReceiptResponseSerializer(serializers.Serializer):
    """Serializer for delivery receipt response data."""

    success = serializers.BooleanField()
    error = serializers.CharField(required=False)


class PurchaseOrderJobSerializer(serializers.Serializer):
    """Serializer for job info within a purchase order listing."""

    job_number = serializers.CharField()
    name = serializers.CharField()
    client = serializers.CharField(allow_blank=True)


class PurchaseOrderListSerializer(serializers.Serializer):
    """Serializer for listing purchase orders from service data."""

    id = serializers.UUIDField()
    po_number = serializers.CharField()
    status = serializers.CharField()
    order_date = serializers.DateField()
    supplier = serializers.CharField()
    supplier_id = serializers.UUIDField(allow_null=True)
    created_by_id = serializers.UUIDField(allow_null=True)
    created_by_name = serializers.CharField(allow_blank=True)
    jobs = PurchaseOrderJobSerializer(many=True)


class PurchaseOrderLastNumberResponseSerializer(serializers.Serializer):
    """Serializer for last purchase order number response."""

    last_po_number = serializers.CharField(allow_null=True, required=False)


class PurchaseOrderLineCreateSerializer(serializers.Serializer):
    """Serializer for creating purchase order lines."""

    job_id = serializers.UUIDField(required=False, allow_null=True)
    description = serializers.CharField(
        max_length=255, required=False, allow_blank=True
    )
    quantity = serializers.DecimalField(max_digits=10, decimal_places=2, default=0)
    unit_cost = serializers.DecimalField(
        max_digits=10, decimal_places=2, required=False, allow_null=True
    )
    price_tbc = serializers.BooleanField(default=False)
    item_code = serializers.CharField(max_length=100, required=False, allow_blank=True)
    metal_type = serializers.CharField(max_length=100, required=False, allow_blank=True)
    alloy = serializers.CharField(max_length=100, required=False, allow_blank=True)
    specifics = serializers.CharField(max_length=255, required=False, allow_blank=True)
    location = serializers.CharField(max_length=255, required=False, allow_blank=True)
    dimensions = serializers.CharField(max_length=255, required=False, allow_blank=True)


class PurchaseOrderLineUpdateSerializer(serializers.Serializer):
    """Serializer for updating purchase order lines (includes ID)."""

    id = serializers.UUIDField(
        required=False, allow_null=True
    )  # Include ID for updates
    job_id = serializers.UUIDField(required=False, allow_null=True)
    description = serializers.CharField(
        max_length=255, required=False, allow_blank=True
    )
    quantity = serializers.DecimalField(max_digits=10, decimal_places=2, default=0)
    unit_cost = serializers.DecimalField(
        max_digits=10, decimal_places=2, required=False, allow_null=True
    )
    price_tbc = serializers.BooleanField(default=False)
    item_code = serializers.CharField(max_length=100, required=False, allow_blank=True)
    metal_type = serializers.CharField(max_length=100, required=False, allow_blank=True)
    alloy = serializers.CharField(max_length=100, required=False, allow_blank=True)
    specifics = serializers.CharField(max_length=255, required=False, allow_blank=True)
    location = serializers.CharField(max_length=255, required=False, allow_blank=True)
    dimensions = serializers.CharField(max_length=255, required=False, allow_blank=True)


class PurchaseOrderCreateSerializer(serializers.Serializer):
    """Serializer for creating purchase orders."""

    supplier_id = serializers.UUIDField(required=False, allow_null=True)
    pickup_address_id = serializers.UUIDField(required=False, allow_null=True)
    reference = serializers.CharField(max_length=255, required=False, allow_blank=True)
    order_date = serializers.DateField(required=False, allow_null=True)
    expected_delivery = serializers.DateField(required=False, allow_null=True)
    lines = PurchaseOrderLineCreateSerializer(many=True, required=False)


class PurchaseOrderCreateResponseSerializer(serializers.Serializer):
    """Serializer for purchase order creation response."""

    id = serializers.UUIDField()
    po_number = serializers.CharField()


class PurchaseOrderUpdateSerializer(serializers.Serializer):
    """Serializer for updating purchase orders."""

    supplier_id = serializers.UUIDField(required=False, allow_null=True)
    pickup_address_id = serializers.UUIDField(required=False, allow_null=True)
    reference = serializers.CharField(max_length=255, required=False, allow_blank=True)
    expected_delivery = serializers.DateField(required=False, allow_null=True)
    status = serializers.CharField(max_length=50, required=False, allow_blank=True)
    lines_to_delete = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        allow_empty=True,
        help_text="List of line IDs to delete",
    )
    lines = PurchaseOrderLineUpdateSerializer(many=True, required=False)


class PurchaseOrderUpdateResponseSerializer(serializers.Serializer):
    """Serializer for purchase order update response."""

    id = serializers.UUIDField()
    status = serializers.CharField()


class AllocationItemSerializer(serializers.Serializer):
    """Serializer for individual allocation items (job or stock)."""

    type = serializers.ChoiceField(choices=[("stock", "Stock"), ("job", "Job")])
    job_id = serializers.UUIDField()
    job_name = serializers.CharField()
    quantity = serializers.FloatField()
    retail_rate = serializers.FloatField(default=0)
    allocation_date = serializers.DateTimeField(allow_null=True)
    description = serializers.CharField()

    # Optional fields for stock allocations
    stock_location = serializers.CharField(required=False, allow_null=True)
    metal_type = serializers.CharField(required=False, allow_null=True)
    alloy = serializers.CharField(required=False, allow_null=True)
    specifics = serializers.CharField(required=False, allow_null=True)

    # Optional field for allocation ID (for deletion purposes)
    allocation_id = serializers.UUIDField(required=False, allow_null=True)


class PurchaseOrderAllocationsResponseSerializer(serializers.Serializer):
    """Serializer for purchase order allocations response."""

    po_id = serializers.UUIDField()
    allocations = serializers.DictField(
        child=serializers.ListField(child=AllocationItemSerializer()),
        help_text="Dictionary where keys are PurchaseOrderLine IDs and values are lists of allocations",
    )


class StockItemSerializer(serializers.ModelSerializer):
    """Serializer for individual stock items."""

    job_id = serializers.UUIDField(source="job.id", read_only=True, allow_null=True)

    class Meta:
        model = Stock
        fields = Stock.STOCK_API_FIELDS + ["job_id"]


class StockListSerializer(serializers.Serializer):
    """Serializer for listing stock items from service data."""

    items = StockItemSerializer(many=True)
    total_count = serializers.IntegerField()


class StockSearchResponseSerializer(serializers.Serializer):
    """Serializer for paginated stock search response."""

    results = StockItemSerializer(many=True)
    count = serializers.IntegerField()
    page = serializers.IntegerField()
    page_size = serializers.IntegerField()
    total_pages = serializers.IntegerField()


class StockCreateSerializer(serializers.Serializer):
    """Serializer for creating stock items."""

    description = serializers.CharField(max_length=255)
    quantity = serializers.DecimalField(max_digits=10, decimal_places=2)
    unit_cost = serializers.DecimalField(max_digits=10, decimal_places=2)
    source = serializers.CharField(max_length=100)
    metal_type = serializers.CharField(max_length=100, required=False, allow_blank=True)
    alloy = serializers.CharField(max_length=100, required=False, allow_blank=True)
    specifics = serializers.CharField(max_length=255, required=False, allow_blank=True)
    location = serializers.CharField(max_length=255, required=False, allow_blank=True)
    dimensions = serializers.CharField(max_length=255, required=False, allow_blank=True)


class StockCreateResponseSerializer(serializers.Serializer):
    """Serializer for stock creation response."""

    id = serializers.UUIDField()


# Additional serializers for purchasing rest views


class PurchasingJobsResponseSerializer(serializers.Serializer):
    """Serializer for PurchasingJobsAPIView response"""

    jobs = JobForPurchasingSerializer(many=True)
    total_count = serializers.IntegerField()


class XeroItemSerializer(serializers.Serializer):
    """Serializer for Xero item data"""

    code = serializers.CharField()
    name = serializers.CharField()
    description = serializers.CharField(required=False, allow_blank=True)
    sales_details = serializers.DictField(required=False)
    purchase_details = serializers.DictField(required=False)


class XeroItemListResponseSerializer(serializers.Serializer):
    """Serializer for XeroItemList response"""

    items = XeroItemSerializer(many=True)
    total_count = serializers.IntegerField(required=False)


class StockDeactivateResponseSerializer(serializers.Serializer):
    """Serializer for stock deactivation response"""

    success = serializers.BooleanField()
    message = serializers.CharField(required=False)


class StockConsumeSerializer(serializers.Serializer):
    """Serializer for stock consumption request"""

    job_id = serializers.UUIDField()
    quantity = serializers.DecimalField(
        max_digits=10, decimal_places=2, min_value=Decimal(0)
    )
    unit_cost = serializers.DecimalField(
        max_digits=10, decimal_places=2, required=False, allow_null=True
    )
    unit_rev = serializers.DecimalField(
        max_digits=10, decimal_places=2, required=False, allow_null=True
    )


class StockConsumeResponseSerializer(serializers.Serializer):
    """Serializer for stock consumption response"""

    success = serializers.BooleanField()
    message = serializers.CharField(required=False)
    remaining_quantity = serializers.DecimalField(
        max_digits=10, decimal_places=2, required=False
    )
    line = CostLineSerializer()


class PurchasingErrorResponseSerializer(serializers.Serializer):
    """Serializer for purchasing error responses"""

    error = serializers.CharField(help_text="Error message")
    details = serializers.CharField(
        required=False, help_text="Optional details about the failure"
    )


# Purchase Order Email and PDF serializers
class PurchaseOrderEmailSerializer(serializers.Serializer):
    """Serializer for purchase order email generation request"""

    recipient_email = serializers.EmailField(required=False)
    message = serializers.CharField(max_length=1000, required=False, allow_blank=True)


class PurchaseOrderEmailResponseSerializer(serializers.Serializer):
    """Serializer for purchase order email generation response"""

    success = serializers.BooleanField()
    email_subject = serializers.CharField(required=False)
    email_body = serializers.CharField(required=False)
    pdf_url = serializers.CharField(required=False)
    message = serializers.CharField(required=False)


class PurchaseOrderPDFResponseSerializer(serializers.Serializer):
    """Serializer for purchase order PDF generation response"""

    # This endpoint returns a PDF file (FileResponse), so this is primarily for documentation
    # The actual response is a binary PDF file, not JSON

    class Meta:
        help_text = "Generates and returns a PDF file for the specified purchase order"


# Allocation deletion serializers
class AllocationDeleteSerializer(serializers.Serializer):
    """Serializer for allocation deletion request"""

    allocation_type = serializers.ChoiceField(
        choices=[("job", "Job"), ("stock", "Stock")],
        help_text="Type of allocation to delete",
    )
    allocation_id = serializers.UUIDField(
        help_text="ID of the Stock item or CostLine to delete"
    )


class AllocationDeleteResponseSerializer(serializers.Serializer):
    """Serializer for allocation deletion response"""

    success = serializers.BooleanField()
    message = serializers.CharField()
    deleted_quantity = serializers.FloatField(required=False)
    description = serializers.CharField(required=False)
    job_name = serializers.CharField(required=False)
    updated_received_quantity = serializers.FloatField(required=False)


class AllocationDetailsResponseSerializer(serializers.Serializer):
    """Serializer for allocation details response"""

    type = serializers.ChoiceField(choices=[("stock", "Stock"), ("job", "Job")])
    id = serializers.UUIDField()
    description = serializers.CharField()
    quantity = serializers.FloatField()
    job_name = serializers.CharField()
    can_delete = serializers.BooleanField()

    # Optional fields for stock allocations
    consumed_by_jobs = serializers.IntegerField(required=False)
    location = serializers.CharField(required=False)

    # Optional fields for job allocations
    unit_cost = serializers.FloatField(required=False)
    unit_revenue = serializers.FloatField(required=False)


# Product Mapping serializers
class ProductMappingSerializer(serializers.Serializer):
    """Serializer for ProductParsingMapping model."""

    id = serializers.UUIDField()
    input_hash = serializers.CharField()
    input_data = serializers.JSONField()
    derived_key = serializers.CharField(allow_null=True)
    mapped_item_code = serializers.CharField(allow_null=True)
    mapped_description = serializers.CharField(allow_null=True)
    mapped_metal_type = serializers.CharField(allow_null=True)
    mapped_alloy = serializers.CharField(allow_null=True)
    mapped_specifics = serializers.CharField(allow_null=True)
    mapped_dimensions = serializers.CharField(allow_null=True)
    mapped_unit_cost = serializers.DecimalField(
        max_digits=10, decimal_places=2, allow_null=True
    )
    mapped_price_unit = serializers.CharField(allow_null=True)
    parser_version = serializers.CharField(allow_null=True)
    parser_confidence = serializers.DecimalField(
        max_digits=3, decimal_places=2, allow_null=True
    )
    is_validated = serializers.BooleanField()
    validated_at = serializers.DateTimeField(allow_null=True)
    validation_notes = serializers.CharField(allow_null=True)
    item_code_is_in_xero = serializers.BooleanField()
    created_at = serializers.DateTimeField()


class ProductMappingListResponseSerializer(serializers.Serializer):
    """Serializer for product mapping list response."""

    items = ProductMappingSerializer(many=True)
    total_count = serializers.IntegerField()
    validated_count = serializers.IntegerField()
    unvalidated_count = serializers.IntegerField()


class ProductMappingValidateSerializer(serializers.Serializer):
    """Serializer for product mapping validation request."""

    mapped_item_code = serializers.CharField(required=False, allow_blank=True)
    mapped_description = serializers.CharField(required=False, allow_blank=True)
    mapped_metal_type = serializers.CharField(required=False, allow_blank=True)
    mapped_alloy = serializers.CharField(required=False, allow_blank=True)
    mapped_specifics = serializers.CharField(required=False, allow_blank=True)
    mapped_dimensions = serializers.CharField(required=False, allow_blank=True)
    mapped_unit_cost = serializers.DecimalField(
        max_digits=10, decimal_places=2, required=False, allow_null=True
    )
    mapped_price_unit = serializers.CharField(required=False, allow_blank=True)
    validation_notes = serializers.CharField(required=False, allow_blank=True)


class ProductMappingValidateResponseSerializer(serializers.Serializer):
    """Serializer for product mapping validation response."""

    success = serializers.BooleanField()
    message = serializers.CharField()
    updated_products_count = serializers.IntegerField(required=False)


# Purchase Order Event serializers
class PurchaseOrderEventSerializer(serializers.ModelSerializer):
    """Serializer for PurchaseOrderEvent model - read-only for frontend."""

    staff = serializers.CharField(
        source="staff.get_display_full_name",
        read_only=True,
    )

    class Meta:
        model = PurchaseOrderEvent
        fields = PurchaseOrderEvent.PURCHASEORDEREVENT_API_FIELDS


class PurchaseOrderEventCreateSerializer(serializers.Serializer):
    """Serializer for purchase order event creation request."""

    description = serializers.CharField(max_length=500)


class PurchaseOrderEventCreateResponseSerializer(serializers.Serializer):
    """Serializer for purchase order event creation response."""

    success = serializers.BooleanField()
    event = PurchaseOrderEventSerializer()


class PurchaseOrderEventsResponseSerializer(serializers.Serializer):
    """Serializer for purchase order events list response."""

    events = PurchaseOrderEventSerializer(many=True)
