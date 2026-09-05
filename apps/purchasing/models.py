"""Purchasing domain models.

Purchase orders, their lines, attached supplier quotes, manual PO events,
and the Stock inventory model.
"""

import logging
import uuid
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVector
from django.db import IntegrityError, models
from django.db.models import IntegerField, Max
from django.db.models.functions import Cast, Substr
from django.utils import timezone

from apps.core.models import CompanyDefaults
from apps.job.enums import MetalType

if TYPE_CHECKING:
    from apps.job.models import Job

logger = logging.getLogger(__name__)


class PurchaseOrder(models.Model):  # noqa: DJ008 -- Purchase orders have no short display label.
    """A request to purchase materials from a supplier.

    API exposure is defined by the ninja schemas for purchasing — the single
    source of PurchaseOrder field lists.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    supplier = models.ForeignKey(
        "company.Company",
        on_delete=models.PROTECT,
        related_name="purchase_orders",
        null=True,
        blank=True,
    )
    pickup_address = models.ForeignKey(
        "company.SupplierPickupAddress",
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
    reference = models.CharField(  # noqa: DJ001 -- restored column is nullable; NULL means unset
        max_length=100,
        blank=True,
        null=True,
        help_text="Optional reference for the purchase order",
    )
    order_date = models.DateField(default=timezone.now)
    expected_delivery = models.DateField(null=True, blank=True)
    xero_id = models.UUIDField(unique=True, null=True, blank=True)
    xero_tenant_id = models.CharField(  # noqa: DJ001 -- restored column is nullable; NULL means unset
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
    xero_last_pushed = models.DateTimeField(
        null=True,
        blank=True,
        help_text=(
            "When our copy of this order last reached Xero. Distinct from "
            "xero_last_synced, which records when we last LOOKED at Xero and is "
            "written on every inbound sync — one column cannot answer both "
            "questions, and using it for both hides an outstanding send behind "
            "the next pull."
        ),
    )
    xero_status = models.CharField(  # noqa: DJ001 -- NULL means Xero has never reported one
        max_length=20,
        null=True,
        blank=True,
        help_text=(
            "Xero's own word for this order (DRAFT, SUBMITTED, AUTHORISED, BILLED, VOIDED). "
            "Separate from `status` because that one answers a different question: whether the "
            "goods arrived and were costed to a job, which only Docketworks knows. Xero saying "
            "BILLED used to set status=fully_received, marking material received that nobody "
            "had receipted."
        ),
    )
    online_url = models.URLField(  # noqa: DJ001 -- restored column is nullable; NULL means unset
        max_length=500, null=True, blank=True
    )
    raw_json = models.JSONField(
        null=True,
        blank=True,
        help_text="Raw JSON data from Xero for this purchase order",
    )

    class Meta:
        constraints: ClassVar = [
            models.CheckConstraint(
                condition=~models.Q(online_url=""),
                name="purchasing_purchaseorder_online_url_not_blank",
            ),
            models.CheckConstraint(condition=~models.Q(reference=""), name="reference_not_blank"),
            models.CheckConstraint(
                condition=~models.Q(xero_tenant_id=""),
                name="purchasing_purchaseorder_xero_tenant_id_not_blank",
            ),
        ]

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Save the model and auto-generate PO number if none exists."""
        if not self.po_number:
            self.po_number = self.generate_po_number()

        super().save(*args, **kwargs)

    @property
    def created_by_name(self) -> str | None:
        """Return the display name of the staff member who created this PO."""
        return self.created_by.get_display_full_name() if self.created_by else None

    def generate_po_number(self) -> str:
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

    # PurchaseOrder.reconcile() is deliberately absent. The former method had
    # that name which iterated ``line.received_lines`` — a related_name no
    # model has ever defined — so it raised AttributeError for any PO with
    # lines, and no backend, frontend, task, or admin caller used it.
    # Deleted as dead code per ADR 0039; the live implementation of "derive the
    # PO status from received quantities" is
    # ``apps.purchasing.services.allocation_service.recompute_purchase_order_status``.


class PurchaseOrderLine(models.Model):  # noqa: DJ008 -- Lines have no useful short display label.
    """A line item on a PO.

    API exposure is defined by the ninja schemas for purchasing — the single
    source of PurchaseOrderLine field lists.
    """

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
    dimensions = models.CharField(  # noqa: DJ001 -- restored column is nullable; NULL means unset
        max_length=255,
        blank=True,
        null=True,
        help_text="Dimensions such as length, width, height, etc.",
    )
    unit_cost = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    price_tbc = models.BooleanField(
        default=False,
        help_text="If true, the price is to be confirmed and unit cost will be None",
    )
    supplier_item_code = models.CharField(  # noqa: DJ001 -- restored column is nullable; NULL means unset
        max_length=50, blank=True, null=True, help_text="Supplier's own item code/SKU"
    )
    item_code = models.CharField(  # noqa: DJ001 -- restored column is nullable; NULL means unset
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
    metal_type = models.CharField(  # noqa: DJ001 -- restored column is nullable; NULL means unset
        max_length=100,
        choices=MetalType.choices,
        blank=True,
        null=True,
    )
    alloy = models.CharField(  # noqa: DJ001 -- restored column is nullable; NULL means unset
        max_length=50,
        blank=True,
        null=True,
        help_text="Alloy specification (e.g., 304, 6061)",
    )
    specifics = models.CharField(  # noqa: DJ001 -- restored column is nullable; NULL means unset
        max_length=255,
        blank=True,
        null=True,
        help_text="Specific details (e.g., m8 countersunk socket screw)",
    )
    location = models.CharField(  # noqa: DJ001 -- restored column is nullable; NULL means unset
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

    class Meta:
        constraints: ClassVar = [
            models.CheckConstraint(
                condition=~models.Q(alloy=""),
                name="purchasing_purchaseorderline_alloy_not_blank",
            ),
            models.CheckConstraint(condition=~models.Q(dimensions=""), name="dimensions_not_blank"),
            models.CheckConstraint(
                condition=~models.Q(item_code=""),
                name="purchasing_purchaseorderline_item_code_not_blank",
            ),
            models.CheckConstraint(
                condition=~models.Q(location=""),
                name="purchasing_purchaseorderline_location_not_blank",
            ),
            models.CheckConstraint(
                condition=~models.Q(metal_type=""),
                name="purchasing_purchaseorderline_metal_type_not_blank",
            ),
            models.CheckConstraint(
                condition=~models.Q(specifics=""),
                name="purchasing_purchaseorderline_specifics_not_blank",
            ),
            models.CheckConstraint(
                condition=~models.Q(supplier_item_code=""),
                name="supplier_item_code_not_blank",
            ),
        ]

    # Note: "Price to be confirmed" prefix was deliberately removed - it cluttered Xero
    @property
    def xero_description(self) -> str:
        """Return the description with job number prefix for Xero sync."""
        if self.job:
            prefix = f"{self.job.job_number} - "
            if self.description.startswith(prefix):
                return self.description
            return f"{prefix}{self.description}"
        return self.description


class PurchaseOrderSupplierQuote(models.Model):  # noqa: DJ008 -- Quote files have no useful short label.
    """A quote file attached to a purchase order."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    purchase_order = models.OneToOneField(
        PurchaseOrder, related_name="supplier_quote", on_delete=models.CASCADE
    )
    filename = models.CharField(max_length=255)
    file_path = models.CharField(max_length=500)
    mime_type = models.CharField(  # noqa: DJ001 -- restored column is nullable; NULL means unset
        max_length=100, blank=True, null=True
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)
    extracted_data = models.JSONField(
        null=True, blank=True, help_text="Extracted data from the quote"
    )
    status = models.CharField(
        max_length=20,
        choices=[("active", "Active"), ("deleted", "Deleted")],
        default="active",
    )

    class Meta:
        constraints: ClassVar = [
            models.CheckConstraint(
                condition=~models.Q(mime_type=""),
                name="purchasing_purchaseordersupplierquote_mime_type_not_blank",
            ),
        ]

    @property
    def full_path(self) -> str:
        """Return the full system path to the file."""
        # DROPBOX_WORKFLOW_FOLDER is not yet defined in v2 settings (v1 reads
        # it from the environment); dynamic access preserves v1's
        # AttributeError-when-unset behaviour pending the port.
        workflow_folder: str = getattr(settings, "DROPBOX_WORKFLOW_FOLDER")  # noqa: B009
        return str(Path(workflow_folder) / self.file_path)

    @property
    def url(self) -> str:
        """Return the URL to serve the file."""
        return f"/purchases/quotes/{self.file_path}"

    @property
    def size(self) -> int | None:
        """Return size of file in bytes."""
        if self.status == "deleted":
            return None

        file_path = Path(self.full_path)
        return file_path.stat().st_size if file_path.exists() else None


class Stock(models.Model):
    """Model for tracking inventory items.

    Each stock item represents a quantity of material that can be assigned to
    jobs. API exposure is defined by the ninja schemas for purchasing — the
    single source of Stock field lists.

    EARLY DRAFT: REVIEW AND TEST
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    job = models.ForeignKey(
        "job.Job",
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

    description = models.CharField(max_length=255, help_text="Description of the stock item")

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

    date = models.DateTimeField(default=timezone.now, help_text="Date the stock item was created")

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
            "Denormalized pointer used to enforce single active stock item per purchase order line."
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
    location = models.TextField(  # noqa: DJ001 -- restored column is nullable; NULL means unset
        blank=True, null=True, help_text="Where we are keeping this"
    )
    metal_type = models.CharField(  # noqa: DJ001 -- restored column is nullable; NULL means unset
        max_length=100,
        choices=MetalType.choices,
        blank=True,
        null=True,
        help_text="Type of metal",
    )
    alloy = models.CharField(  # noqa: DJ001 -- restored column is nullable; NULL means unset
        max_length=50,
        blank=True,
        null=True,
        help_text="Alloy specification (e.g., 304, 6061)",
    )
    specifics = models.CharField(  # noqa: DJ001 -- restored column is nullable; NULL means unset
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
    parser_attempted_at = models.DateTimeField(
        blank=True,
        null=True,
        help_text="When this inventory item was last attempted by the LLM parser",
    )
    parsed_at = models.DateTimeField(
        blank=True, null=True, help_text="When this inventory item was parsed by LLM"
    )
    parser_version = models.CharField(  # noqa: DJ001 -- restored column is nullable; NULL means unset
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

    # Not indexed: Stock is < 10k rows at our scale and the freshness query also
    # does Count(id) (to catch deletions), which scans regardless. Revisit if
    # the table grows materially or if Max(updated_at) shows up in profiling.
    updated_at = models.DateTimeField(
        auto_now=True,
        null=True,
        help_text=(
            "Auto-bumped on every save(); feeds the /api/data-versions/ "
            "freshness signal so the frontend stockStore can detect catalogue "
            "changes (e.g. Xero unit_cost updates) and refetch."
        ),
    )

    # TODO: Add fields for:
    # - Location
    # - Minimum stock level
    # - Reorder point
    # - Category/Type
    # - Unit of measure

    # Stock holding job name
    STOCK_HOLDING_JOB_NAME = "Worker Admin"
    _stock_holding_job: ClassVar["Job | None"] = None

    class Meta:
        constraints: ClassVar = [
            models.UniqueConstraint(fields=["xero_id"], name="unique_xero_id_stock"),
            models.UniqueConstraint(
                fields=["active_source_purchase_order_line_id"],
                name="unique_active_stock_per_po_line",
            ),
            models.CheckConstraint(
                condition=~models.Q(alloy=""), name="purchasing_stock_alloy_not_blank"
            ),
            models.CheckConstraint(
                condition=~models.Q(item_code=""), name="purchasing_stock_item_code_not_blank"
            ),
            models.CheckConstraint(
                condition=~models.Q(location=""), name="purchasing_stock_location_not_blank"
            ),
            models.CheckConstraint(
                condition=~models.Q(metal_type=""), name="purchasing_stock_metal_type_not_blank"
            ),
            models.CheckConstraint(
                condition=~models.Q(parser_version=""),
                name="purchasing_stock_parser_version_not_blank",
            ),
            models.CheckConstraint(
                condition=~models.Q(specifics=""), name="purchasing_stock_specifics_not_blank"
            ),
            models.CheckConstraint(
                condition=~models.Q(xero_id=""), name="purchasing_stock_xero_id_not_blank"
            ),
        ]
        indexes: ClassVar = [
            GinIndex(
                SearchVector("description", weight="A", config="english")
                + SearchVector("item_code", weight="A", config="english")
                + SearchVector("metal_type", weight="B", config="english")
                + SearchVector("alloy", weight="B", config="english")
                + SearchVector("specifics", weight="B", config="english")
                + SearchVector("location", weight="C", config="english"),
                name="stock_fts_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.description} ({self.quantity})"

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Override save to add logging and validation."""
        logger.debug("Saving stock item: %s", self.description)

        desired_active_ref = (
            self.source_purchase_order_line_id
            if self.is_active and self.source_purchase_order_line_id
            else None
        )
        needs_active_ref_update = self.active_source_purchase_order_line_id != desired_active_ref
        self.active_source_purchase_order_line_id = desired_active_ref

        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            extras: tuple[str, ...] = ("updated_at",)
            if needs_active_ref_update:
                extras = ("active_source_purchase_order_line_id", *extras)
            merged = tuple(update_fields) + extras
            deduped = tuple(dict.fromkeys(merged))
            kwargs["update_fields"] = deduped

        # Log negative quantities but allow them (backorders, emergency usage, etc.)
        if self.quantity < 0:
            logger.info(
                "Stock item has negative quantity: %s (%s)", self.quantity, self.description
            )

        # Stock.unit_cost is NOT NULL: catch a caller that omitted it here, with
        # a message naming the field, rather than letting the negative-check
        # raise "'<' not supported between NoneType and int" (ADR 0015/0038).
        if self.unit_cost is None:
            raise ValueError("Stock requires a unit cost")

        # Validate unit cost is not negative
        if self.unit_cost < 0:
            logger.warning(
                "Attempted to save stock item with negative unit cost: %s", self.unit_cost
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
        logger.info("Saved stock item: %s", self.description)

    @property
    def retail_rate(self) -> Decimal:
        """Calculate markup rate from unit_cost and unit_revenue."""
        if self.unit_cost and self.unit_cost > 0 and self.unit_revenue:
            return (self.unit_revenue - self.unit_cost) / self.unit_cost
        raise ValueError("Unit cost must be set and greater than zero to calculate retail rate")

    @retail_rate.setter
    def retail_rate(self, value: Any) -> None:
        """Set unit_revenue based on unit_cost and markup rate."""
        if self.unit_cost and self.unit_cost > 0:
            # Ensure value is converted to Decimal for proper arithmetic
            try:
                # All non-Decimal numeric inputs share the same conversion path.
                decimal_value = value if isinstance(value, Decimal) else Decimal(str(value))

                self.unit_revenue = self.unit_cost * (Decimal("1") + decimal_value)
            except (ValueError, TypeError, InvalidOperation) as e:
                raise ValueError(
                    f"Invalid retail rate value: {value} (type: {type(value)}). Error: {e}"
                ) from e
        else:
            raise ValueError("Unit cost must be set and greater than zero to set retail rate")

    @classmethod
    def get_stock_holding_job(cls) -> "Job":
        """Return the job designated for holding general stock.

        This is a utility method to avoid repeating the job lookup across the
        codebase. Uses a class-level cache to avoid repeated database queries.
        """
        from apps.job.models import Job  # noqa: PLC0415 -- avoids job <-> purchasing import cycle

        if cls._stock_holding_job is None:
            cls._stock_holding_job = Job.objects.get(name=cls.STOCK_HOLDING_JOB_NAME)
        return cls._stock_holding_job


class PurchaseOrderEvent(models.Model):
    """A manual note/comment on a purchase order.

    Simpler than JobEvent - no delta tracking or undo support needed.
    API exposure is defined by the ninja schemas for purchasing.
    """

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

    class Meta:
        ordering: ClassVar = ["-timestamp"]
        indexes: ClassVar = [
            models.Index(
                fields=["purchase_order", "-timestamp"],
                name="poevent_po_timestamp_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.timestamp}: Event for PO {self.purchase_order.po_number}"
