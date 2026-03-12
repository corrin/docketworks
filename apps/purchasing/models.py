import logging
import os
import uuid
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import IntegrityError, models
from django.db.models import IntegerField, Max
from django.db.models.functions import Cast, Substr
from django.utils import timezone

from apps.job.enums import MetalType
from apps.job.models import Job
from apps.workflow.models import CompanyDefaults

logger = logging.getLogger(__name__)


class PurchaseOrder(models.Model):
    """A request to purchase materials from a supplier."""

    # CHECKLIST - when adding a new field or property to PurchaseOrder, check these locations:
    #   1. PURCHASEORDER_API_FIELDS or PURCHASEORDER_INTERNAL_FIELDS below (if it's a model field)
    #   2. PurchaseOrderSerializer in apps/purchasing/serializers.py (uses PURCHASEORDER_API_FIELDS)
    #   3. PurchaseOrderListSerializer in apps/purchasing/serializers.py (subset for lists)
    #   4. list_purchase_orders() in apps/purchasing/services/purchasing_rest_service.py
    #   5. create_purchase_order() in apps/purchasing/services/purchasing_rest_service.py
    #   6. update_purchase_order() in apps/purchasing/services/purchasing_rest_service.py
    #   7. get_xero_document() in apps/workflow/views/xero/xero_po_manager.py (Xero API format)
    #   8. PurchaseOrderPDFGenerator in apps/purchasing/services/purchase_order_pdf_service.py
    #   9. create_purchase_order_email() in apps/purchasing/services/purchase_order_email_service.py
    #
    # Database fields exposed via API serializers
    PURCHASEORDER_API_FIELDS = [
        "id",
        "po_number",
        "reference",
        "status",
        "order_date",
        "expected_delivery",
        "online_url",
        "xero_id",
        "pickup_address_id",
        "created_by_id",
    ]

    # Computed properties exposed via API serializers
    PURCHASEORDER_API_PROPERTIES = [
        "supplier",
        "supplier_id",
        "supplier_has_xero_id",
        "lines",
        "pickup_address",
        "created_by_name",
    ]

    # Internal fields not exposed in API
    PURCHASEORDER_INTERNAL_FIELDS = [
        "job",
        "created_by",
        "xero_tenant_id",
        "created_at",
        "updated_at",
        "xero_last_modified",
        "xero_last_synced",
        "raw_json",
    ]

    # All PurchaseOrder model fields (derived)
    PURCHASEORDER_ALL_FIELDS = PURCHASEORDER_API_FIELDS + PURCHASEORDER_INTERNAL_FIELDS

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    supplier = models.ForeignKey(
        "client.Client",
        on_delete=models.PROTECT,
        related_name="purchase_orders",
        null=True,
        blank=True,
    )
    pickup_address = models.ForeignKey(
        "client.SupplierPickupAddress",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="purchase_orders",
        help_text="Delivery/pickup address for this purchase order",
    )
    job = models.ForeignKey(
        "job.Job",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="Primary job this PO is for",
    )
    created_by = models.ForeignKey(
        "accounts.Staff",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="created_purchase_orders",
        help_text="Staff member who created this purchase order",
    )
    po_number = models.CharField(max_length=50, unique=True)
    reference = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Optional reference for the purchase order",
    )
    order_date = models.DateField(default=timezone.now)
    expected_delivery = models.DateField(null=True, blank=True)
    xero_id = models.UUIDField(unique=True, null=True, blank=True)
    xero_tenant_id = models.CharField(
        max_length=255, null=True, blank=True
    )  # For reference only - we are not fully multi-tenant yet
    status = models.CharField(
        max_length=20,
        choices=[
            ("draft", "Draft"),
            ("submitted", "Submitted to Supplier"),
            ("partially_received", "Partially Received"),
            ("fully_received", "Fully Received"),
            ("deleted", "Deleted"),
        ],
        default="draft",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    xero_last_modified = models.DateTimeField(null=True, blank=True)
    xero_last_synced = models.DateTimeField(null=True, blank=True, default=timezone.now)
    online_url = models.URLField(max_length=500, null=True, blank=True)
    raw_json = models.JSONField(
        null=True,
        blank=True,
        help_text="Raw JSON data from Xero for this purchase order",
    )

    @property
    def created_by_name(self) -> str | None:
        """Return the display name of the staff member who created this PO."""
        return self.created_by.get_display_full_name() if self.created_by else None

    def generate_po_number(self):
        """Generate the next sequential PO number based on the configured prefix."""
        defaults = CompanyDefaults.get_solo()
        start = defaults.starting_po_number
        po_prefix = defaults.po_prefix  # Get prefix from CompanyDefaults

        prefix_len = len(po_prefix)

        # 1) Filter to exactly <prefix><digits> (removed hyphen from regex)
        # 2) Strip off "<prefix>" (first prefix_len chars), cast the rest to int
        # 3) Take the MAX of that numeric part
        agg = (
            PurchaseOrder.objects.filter(po_number__regex=rf"^{po_prefix}\d+$")
            .annotate(num=Cast(Substr("po_number", prefix_len + 1), IntegerField()))
            .aggregate(max_num=Max("num"))
        )
        max_existing = agg["max_num"] or 0

        nxt = max(start, max_existing + 1)
        return f"{po_prefix}{nxt:04d}"  # Use the dynamic prefix

    def save(self, *args, **kwargs):
        """Save the model and auto-generate PO number if none exists."""
        if not self.po_number:
            self.po_number = self.generate_po_number()

        super().save(*args, **kwargs)

    def reconcile(self):
        """Check received quantities against ordered quantities."""
        for line in self.po_lines.all():
            total_received = sum(
                po_line.quantity for po_line in line.received_lines.all()
            )
            if total_received > line.quantity:
                return "Over"
            elif total_received < line.quantity:
                return "Partial"

        self.status = "fully_received"
        self.save()
        return "Reconciled"

    class Meta:
        db_table = "workflow_purchaseorder"


class PurchaseOrderLine(models.Model):
    """A line item on a PO."""

    # CHECKLIST - when adding a new field or property to PurchaseOrderLine, check these locations:
    #   1. PURCHASEORDERLINE_API_FIELDS or PURCHASEORDERLINE_INTERNAL_FIELDS below (if it's a model field)
    #   2. PurchaseOrderLineSerializer in apps/purchasing/serializers.py (uses PURCHASEORDERLINE_API_FIELDS)
    #   3. PurchaseOrderLineCreateSerializer in apps/purchasing/serializers.py (create fields)
    #   4. PurchaseOrderLineUpdateSerializer in apps/purchasing/serializers.py (update fields)
    #   5. FIELD_UPDATERS in apps/purchasing/services/purchasing_rest_service.py
    #   6. _create_line() in apps/purchasing/services/purchasing_rest_service.py
    #   7. get_line_items() in apps/workflow/views/xero/xero_po_manager.py (Xero API format)
    #   8. add_line_items_table() in apps/purchasing/services/purchase_order_pdf_service.py
    #
    # Fields exposed via API serializers
    PURCHASEORDERLINE_API_FIELDS = [
        "id",
        "description",
        "quantity",
        "dimensions",
        "unit_cost",
        "price_tbc",
        "supplier_item_code",
        "item_code",
        "received_quantity",
        "metal_type",
        "alloy",
        "specifics",
        "location",
    ]

    # Internal fields not exposed in API
    PURCHASEORDERLINE_INTERNAL_FIELDS = [
        "purchase_order",
        "job",
        "raw_line_data",
        "xero_line_item_id",
    ]

    # All PurchaseOrderLine model fields (derived)
    PURCHASEORDERLINE_ALL_FIELDS = (
        PURCHASEORDERLINE_API_FIELDS + PURCHASEORDERLINE_INTERNAL_FIELDS
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    purchase_order = models.ForeignKey(
        "purchasing.PurchaseOrder", on_delete=models.CASCADE, related_name="po_lines"
    )
    job = models.ForeignKey(
        "job.Job",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="purchase_order_lines",
        help_text="The job this purchase line is for",
    )
    description = models.CharField(max_length=200)
    quantity = models.DecimalField(max_digits=10, decimal_places=2)
    dimensions = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Dimensions such as length, width, height, etc.",
    )
    unit_cost = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    price_tbc = models.BooleanField(
        default=False,
        help_text="If true, the price is to be confirmed and unit cost will be None",
    )
    supplier_item_code = models.CharField(
        max_length=50, blank=True, null=True, help_text="Supplier's own item code/SKU"
    )
    item_code = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        help_text="Internal item code for Xero integration",
    )
    received_quantity = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        help_text="Total quantity received against this line",
    )
    metal_type = models.CharField(
        max_length=100,
        choices=MetalType.choices,
        default=MetalType.UNSPECIFIED,
        blank=True,
        null=True,
    )
    alloy = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text="Alloy specification (e.g., 304, 6061)",
    )
    specifics = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Specific details (e.g., m8 countersunk socket screw)",
    )
    location = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Where this item will be stored",
    )
    raw_line_data = models.JSONField(
        null=True,
        blank=True,
        help_text="Raw JSON data from the source system or document",
    )
    xero_line_item_id = models.UUIDField(
        null=True,
        blank=True,
        db_index=True,
        help_text="Xero's unique identifier for this line item (from line_item_id)",
    )

    # Note: "Price to be confirmed" prefix was deliberately removed - it cluttered Xero
    @property
    def xero_description(self) -> str:
        """Description with job number prefix for Xero sync."""
        if self.job:
            prefix = f"{self.job.job_number} - "
            if self.description.startswith(prefix):
                return self.description
            return f"{prefix}{self.description}"
        return self.description

    class Meta:
        db_table = "workflow_purchaseorderline"


class PurchaseOrderSupplierQuote(models.Model):
    """A quote file attached to a purchase order."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    purchase_order = models.OneToOneField(
        PurchaseOrder, related_name="supplier_quote", on_delete=models.CASCADE
    )
    filename = models.CharField(max_length=255)
    file_path = models.CharField(max_length=500)
    mime_type = models.CharField(max_length=100, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    extracted_data = models.JSONField(
        null=True, blank=True, help_text="Extracted data from the quote"
    )
    status = models.CharField(
        max_length=20,
        choices=[("active", "Active"), ("deleted", "Deleted")],
        default="active",
    )

    @property
    def full_path(self):
        """Full system path to the file."""
        return os.path.join(settings.DROPBOX_WORKFLOW_FOLDER, self.file_path)

    @property
    def url(self):
        """URL to serve the file."""
        return f"/purchases/quotes/{self.file_path}"

    @property
    def size(self):
        """Return size of file in bytes."""
        if self.status == "deleted":
            return None

        file_path = self.full_path
        return os.path.getsize(file_path) if os.path.exists(file_path) else None

    class Meta:
        db_table = "workflow_purchaseordersupplierquote"


class Stock(models.Model):
    """
    Model for tracking inventory items.
    Each stock item represents a quantity of material that can be assigned to jobs.

    EARLY DRAFT: REVIEW AND TEST
    """

    # CHECKLIST - when adding a new field or property to Stock, check these locations:
    #   1. STOCK_API_FIELDS or STOCK_INTERNAL_FIELDS below (if it's a model field)
    #   2. StockItemSerializer in apps/purchasing/serializers.py (uses STOCK_API_FIELDS)
    #   3. StockCreateSerializer in apps/purchasing/serializers.py (create fields)
    #   4. create_stock() in apps/purchasing/services/purchasing_rest_service.py
    #   5. _create_stock_from_allocation() in apps/purchasing/services/delivery_receipt_service.py
    #   6. get_allocation_details() in apps/purchasing/services/allocation_service.py (subset)
    #   7. sync_stock_to_xero() in apps/workflow/api/xero/stock_sync.py (Xero API format)
    #   8. transform_stock() in apps/workflow/api/xero/sync.py (sync from Xero)
    #   9. consume_stock() in apps/purchasing/services/stock_service.py
    #
    # Fields exposed via API serializers
    STOCK_API_FIELDS = [
        "id",
        "item_code",
        "description",
        "quantity",
        "unit_cost",
        "unit_revenue",
        "date",
        "source",
        "location",
        "metal_type",
        "alloy",
        "specifics",
        "is_active",
    ]

    # Internal fields not exposed in API
    STOCK_INTERNAL_FIELDS = [
        "job",
        "source_purchase_order_line",
        "active_source_purchase_order_line_id",
        "source_parent_stock",
        "xero_id",
        "xero_last_modified",
        "xero_last_synced",
        "raw_json",
        "xero_inventory_tracked",
        "parsed_at",
        "parser_version",
        "parser_confidence",
    ]

    # All Stock model fields (derived)
    STOCK_ALL_FIELDS = STOCK_API_FIELDS + STOCK_INTERNAL_FIELDS

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    job = models.ForeignKey(
        Job,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stock_items",
        help_text="The job this stock item is assigned to",
    )

    item_code = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        unique=True,
        help_text="Xero Item Code",
    )

    description = models.CharField(
        max_length=255, help_text="Description of the stock item"
    )

    quantity = models.DecimalField(
        max_digits=10, decimal_places=2, help_text="Current quantity of the stock item"
    )

    unit_cost = models.DecimalField(
        max_digits=10, decimal_places=2, help_text="Cost per unit of the stock item"
    )

    unit_revenue = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Revenue per unit (what customer pays)",
    )

    date = models.DateTimeField(
        default=timezone.now, help_text="Date the stock item was created"
    )

    source = models.CharField(
        max_length=50,
        choices=[
            ("purchase_order", "Purchase Order Receipt"),
            ("split_from_stock", "Split/Offcut from Stock"),
            ("manual", "Manual Adjustment/Stocktake"),
            ("product_catalog", "Product Catalog"),
        ],
        help_text="Origin of this stock item",
    )

    source_purchase_order_line = models.ForeignKey(
        "purchasing.PurchaseOrderLine",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stock_generated",
        help_text="The PO line this stock originated from (if source='purchase_order')",
    )
    active_source_purchase_order_line_id = models.UUIDField(
        null=True,
        blank=True,
        editable=False,
        help_text=(
            "Denormalized pointer used to enforce single active stock item per "
            "purchase order line."
        ),
    )
    source_parent_stock = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="child_stock_splits",
        help_text="The parent stock item this was split from (if source='split_from_stock')",
    )
    location = models.TextField(blank=True, help_text="Where we are keeping this")
    metal_type = models.CharField(
        max_length=100,
        choices=MetalType.choices,
        default=MetalType.UNSPECIFIED,
        blank=True,
        help_text="Type of metal",
    )
    alloy = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text="Alloy specification (e.g., 304, 6061)",
    )
    specifics = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Specific details (e.g., m8 countersunk socket screw)",
    )
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text="False when quantity reaches zero or item is fully consumed/transformed",
    )

    xero_id = models.CharField(
        max_length=255,
        unique=True,
        null=True,
        blank=True,
        help_text="Unique ID from Xero for this item",
    )
    xero_last_modified = models.DateTimeField(
        null=True, blank=True, help_text="Last modified date from Xero for this item"
    )
    xero_last_synced = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When this item was last synced with Xero (None = never synced)",
    )
    raw_json = models.JSONField(
        null=True, blank=True, help_text="Raw JSON data from Xero for this item"
    )
    xero_inventory_tracked = models.BooleanField(
        default=False, help_text="Whether this item is inventory-tracked in Xero"
    )

    # Parser tracking fields
    parsed_at = models.DateTimeField(
        blank=True, null=True, help_text="When this inventory item was parsed by LLM"
    )
    parser_version = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text="Version of parser used for this data",
    )
    parser_confidence = models.DecimalField(
        max_digits=3,
        decimal_places=2,
        blank=True,
        null=True,
        help_text="Parser confidence score 0.00-1.00",
    )

    # TODO: Add fields for:
    # - Location
    # - Minimum stock level
    # - Reorder point
    # - Category/Type
    # - Unit of measure

    def __str__(self):
        return f"{self.description} ({self.quantity})"

    @property
    def retail_rate(self):
        """Calculate markup rate from unit_cost and unit_revenue"""
        if self.unit_cost and self.unit_cost > 0 and self.unit_revenue:
            return (self.unit_revenue - self.unit_cost) / self.unit_cost
        else:
            raise ValueError(
                "Unit cost must be set and greater than zero to calculate retail rate"
            )

    @retail_rate.setter
    def retail_rate(self, value):
        """Set unit_revenue based on unit_cost and markup rate"""
        if self.unit_cost and self.unit_cost > 0:
            # Ensure value is converted to Decimal for proper arithmetic
            try:
                if isinstance(value, Decimal):
                    decimal_value = value
                elif isinstance(value, (int, float)):
                    decimal_value = Decimal(str(value))
                else:
                    decimal_value = Decimal(str(value))

                self.unit_revenue = self.unit_cost * (Decimal("1") + decimal_value)
            except (ValueError, TypeError, InvalidOperation) as e:
                raise ValueError(
                    f"Invalid retail rate value: {value} (type: {type(value)}). Error: {e}"
                )
        else:
            raise ValueError(
                "Unit cost must be set and greater than zero to set retail rate"
            )

    def save(self, *args, **kwargs):
        """
        Override save to add logging and validation.
        """
        logger.debug(f"Saving stock item: {self.description}")

        desired_active_ref = (
            self.source_purchase_order_line_id
            if self.is_active and self.source_purchase_order_line_id
            else None
        )
        needs_active_ref_update = (
            self.active_source_purchase_order_line_id != desired_active_ref
        )
        self.active_source_purchase_order_line_id = desired_active_ref

        update_fields = kwargs.get("update_fields")
        if update_fields is not None and needs_active_ref_update:
            field_name = "active_source_purchase_order_line_id"
            merged = tuple(update_fields) + (field_name,)
            deduped = tuple(dict.fromkeys(merged))
            kwargs["update_fields"] = deduped

        # Log negative quantities but allow them (backorders, emergency usage, etc.)
        if self.quantity < 0:
            logger.info(
                f"Stock item has negative quantity: {self.quantity} ({self.description})"
            )

        # Validate unit cost is not negative
        if self.unit_cost < 0:
            logger.warning(
                f"Attempted to save stock item with negative unit cost: {self.unit_cost}"
            )
            raise ValueError("Unit cost cannot be negative")

        try:
            super().save(*args, **kwargs)
        except IntegrityError as exc:
            if "unique_active_stock_per_po_line" in str(exc):
                raise IntegrityError(
                    "An active stock entry already exists for this purchase order line."
                ) from exc
            raise
        logger.info(f"Saved stock item: {self.description}")

    # Stock holding job name
    STOCK_HOLDING_JOB_NAME = "Worker Admin"
    _stock_holding_job = None

    @classmethod
    def get_stock_holding_job(cls):
        """
        Returns the job designated for holding general stock.
        This is a utility method to avoid repeating the job lookup across the codebase.
        Uses a class-level cache to avoid repeated database queries.
        """
        if cls._stock_holding_job is None:
            cls._stock_holding_job = Job.objects.get(name=cls.STOCK_HOLDING_JOB_NAME)
        return cls._stock_holding_job

    class Meta:
        db_table = "workflow_stock"
        constraints = [
            models.UniqueConstraint(fields=["xero_id"], name="unique_xero_id_stock"),
            models.UniqueConstraint(
                fields=["active_source_purchase_order_line_id"],
                name="unique_active_stock_per_po_line",
            ),
        ]


class PurchaseOrderEvent(models.Model):
    """A manual note/comment on a purchase order.

    Simpler than JobEvent - no delta tracking or undo support needed.
    """

    # CHECKLIST - when adding a new field to PurchaseOrderEvent:
    #   1. PURCHASEORDEREVENT_API_FIELDS below
    #   2. PurchaseOrderEventSerializer in apps/purchasing/serializers.py
    #
    PURCHASEORDEREVENT_API_FIELDS = [
        "id",
        "description",
        "timestamp",
        "staff",
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    purchase_order = models.ForeignKey(
        PurchaseOrder,
        on_delete=models.CASCADE,
        related_name="events",
    )
    timestamp = models.DateTimeField(default=timezone.now)
    staff = models.ForeignKey(
        "accounts.Staff",
        on_delete=models.PROTECT,
    )
    description = models.TextField()

    def __str__(self) -> str:
        return f"{self.timestamp}: Event for PO {self.purchase_order.po_number}"

    class Meta:
        db_table = "workflow_purchaseorderevent"
        ordering = ["-timestamp"]
        indexes = [
            models.Index(
                fields=["purchase_order", "-timestamp"],
                name="poevent_po_timestamp_idx",
            ),
        ]
