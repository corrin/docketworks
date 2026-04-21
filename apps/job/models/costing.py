import logging
import uuid
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from .costline_validators import (
    validate_costline_ext_refs,
    validate_costline_meta,
)

logger = logging.getLogger(__name__)


def get_default_cost_set_summary():
    """Default summary structure for CostSet."""
    return {"cost": 0.0, "rev": 0.0, "hours": 0.0}


class CostSet(models.Model):
    """
    Represents a set of costs for a job in a specific revision.
    Can be an estimate, quote or actual cost.
    """

    # CHECKLIST - when adding a new field or property to CostSet, check these locations:
    #   1. COSTSET_ALL_FIELDS below (if it's a model field)
    #   2. CostSetSerializer in apps/job/serializers/costing_serializer.py
    #   3. QuoteImportStatusResponseSerializer in apps/job/serializers/costing_serializer.py (subset)
    #   4. get_job_costing() in apps/job/services/job_rest_service.py
    #   5. _ensure_actual_costset() in apps/purchasing/services/delivery_receipt_service.py
    #   6. Job.get_latest() method in apps/job/models/job.py (returns CostSet)
    #
    # All CostSet model fields for serialization.
    COSTSET_ALL_FIELDS = [
        "id",
        "job",
        "kind",
        "rev",
        "summary",
        "created",
    ]

    KIND_CHOICES = [
        ("estimate", "Estimate"),
        ("quote", "Quote"),
        ("actual", "Actual"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.ForeignKey(
        "job.Job", on_delete=models.CASCADE, related_name="cost_sets"
    )
    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    rev = models.IntegerField()
    summary = models.JSONField(
        default=get_default_cost_set_summary,
        help_text="Summary data for this cost set (cost, rev, hours)",
    )
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["job", "kind", "rev"], name="unique_job_kind_rev"
            )
        ]
        ordering = ["-created"]

    def __str__(self):
        return f"{self.job.name} - {self.get_kind_display()} Rev {self.rev}"

    def clean(self):
        if self.rev < 0:
            raise ValidationError("Revision must be non-negative")

    @property
    def total_cost(self):
        """Total internal cost for all cost lines in this set"""
        return sum(cost_line.total_cost for cost_line in self.cost_lines.all())

    @property
    def total_revenue(self):
        """Total revenue (charge amount) for all cost lines in this set"""
        return sum(cost_line.total_rev for cost_line in self.cost_lines.all())


class CostLine(models.Model):
    """
    Represents a cost line within a CostSet.
    Can be time, material or adjustment.

    Meta Field Structure by Kind:

    TIME (kind='time'):
        - staff_id (str, UUID): Reference to Staff member who performed the work
        - date (str, ISO date): Date the work was performed (legacy, use accounting_date field)
        - is_billable (bool): Whether this time is billable to the client
        - start_time (str, ISO time): Start time of the timesheet entry
        - end_time (str, ISO time): End time of the timesheet entry
        - wage_rate_multiplier (float): Multiplier for staff wage rate (e.g., 1.5 for overtime)
        - note (str): Optional notes about the time entry
        - created_from_timesheet (bool): True if created via modern timesheet interface
        - wage_rate (float): Wage rate at time of entry (for timesheet entries)
        - charge_out_rate (float): Charge-out rate at time of entry (for timesheet entries)

    MATERIAL (kind='material'):
        - item_code (str): Stock item code reference
        - comments (str): Notes about the material usage
        - source (str): Origin of the material entry ('delivery_receipt' for PO deliveries)
        - retail_rate (float): Retail markup rate applied (e.g., 0.2 for 20%)
        - po_number (str): Purchase order reference number
        - consumed_by (str): Reference to what consumed this material

    ADJUSTMENT (kind='adjust'):
        - comments (str): Explanation of the adjustment
        - source (str): Origin of adjustment ('manual_adjustment' for user-created)
    """

    # CHECKLIST - when adding a new field or property to CostLine, check these locations:
    #   1. COSTLINE_API_FIELDS or COSTLINE_INTERNAL_FIELDS below (if it's a model field)
    #   2. CostLineSerializer in apps/job/serializers/costing_serializer.py (uses COSTLINE_API_FIELDS)
    #   3. TimesheetCostLineSerializer in apps/job/serializers/costing_serializer.py (extends API fields)
    #   4. CostLineCreateUpdateSerializer in apps/job/serializers/costing_serializer.py (write fields)
    #   5. _get_staff_timesheet_data() in apps/timesheet/services/daily_timesheet_service.py
    #   6. _create_costline_from_allocation() in apps/purchasing/services/delivery_receipt_service.py
    #   7. consume_stock() in apps/purchasing/services/stock_service.py
    #   8. get_allocation_details() in apps/purchasing/services/allocation_service.py (subset)
    #   9. _process_time_entries() in apps/timesheet/services/weekly_timesheet_service.py
    #  10. sync_time_entries_from_xero() in apps/workflow/api/xero/sync.py (Xero format)
    #  11. JobRestService.create_job() in apps/job/services/job_rest_service.py (estimate time lines)
    #  12. WorkshopTimesheetService.create_entry() in apps/job/services/workshop_service.py
    #  13. _create_cost_line_from_draft() and _copy_cost_line() in apps/job/diff.py
    #  14. _copy_estimate_to_quote_costset() in apps/job/services/quote_sync_service.py
    #
    # Fields exposed via API serializers
    COSTLINE_API_FIELDS = [
        "id",
        "kind",
        "desc",
        "quantity",
        "unit_cost",
        "unit_rev",
        "ext_refs",
        "meta",
        "created_at",
        "updated_at",
        "accounting_date",
        "xero_time_id",
        "xero_expense_id",
        "xero_last_modified",
        "xero_last_synced",
        "approved",
        "xero_pay_item",
    ]

    # Internal fields not exposed in API
    COSTLINE_INTERNAL_FIELDS = [
        "cost_set",
    ]

    # All CostLine model fields (derived)
    COSTLINE_ALL_FIELDS = COSTLINE_API_FIELDS + COSTLINE_INTERNAL_FIELDS

    KIND_CHOICES = [
        ("time", "Time"),
        ("material", "Material"),
        ("adjust", "Adjustment"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    cost_set = models.ForeignKey(
        CostSet, on_delete=models.CASCADE, related_name="cost_lines"
    )
    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    desc = models.CharField(
        max_length=255, help_text="Description of this cost line", blank=True
    )
    quantity = models.DecimalField(
        max_digits=10, decimal_places=3, default=Decimal("1.000")
    )
    unit_cost = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("0.00")
    )
    unit_rev = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("0.00")
    )
    ext_refs = models.JSONField(
        default=dict,
        blank=True,
        help_text="External references (e.g., time entry IDs, material IDs)",
    )
    meta = models.JSONField(
        default=dict,
        blank=True,
        help_text="Additional metadata - structure varies by kind (see class docstring)",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Accounting date - the date this cost should be attributed to for reporting
    accounting_date = models.DateField(
        help_text="The date this cost should be attributed to for accounting purposes",
    )

    # Xero sync fields for bidirectional time/expense tracking
    xero_time_id = models.CharField(max_length=255, null=True, blank=True)
    xero_expense_id = models.CharField(max_length=255, null=True, blank=True)
    xero_last_modified = models.DateTimeField(null=True, blank=True)
    xero_last_synced = models.DateTimeField(null=True, blank=True, default=timezone.now)

    approved = models.BooleanField(
        default=True,
        help_text="Indicates whether this line is approved or not by an office staff (when the line is created by a workshop worker)",
    )

    # Xero pay item - determines how this time entry is paid (leave type, overtime, etc.)
    xero_pay_item = models.ForeignKey(
        "workflow.XeroPayItem",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cost_lines",
        help_text="The Xero pay item for this time entry (leave type, earnings rate, etc.)",
    )

    class Meta:
        indexes = [
            models.Index(fields=["cost_set_id", "kind"]),
            models.Index(fields=["cost_set_id", "created_at"]),
            models.Index(fields=["cost_set_id", "kind", "created_at"]),
        ]
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"{self.cost_set} - {self.get_kind_display()}: {self.desc}"

    @property
    def total_cost(self):
        """Calculates total cost (quantity * unit cost)"""
        return self.quantity * self.unit_cost

    @property
    def total_rev(self):
        """Calculates total revenue (quantity * unit revenue)"""
        return self.quantity * self.unit_rev

    def clean(self):
        super().clean()
        # Log negative quantities but allow them (for adjustments, corrections, returns, etc.)
        if self.quantity < 0:
            logger.warning(
                f"CostLine has negative quantity: {self.quantity} for {self.desc}"
            )

        if (
            self.kind == "time"
            and self.cost_set.kind == "actual"
            and self.xero_pay_item is None
        ):
            raise ValidationError("Actual time entries must have xero_pay_item set.")

        validate_costline_meta(self.meta, self.kind)
        validate_costline_ext_refs(self.ext_refs)

    def _update_cost_set_summary(self) -> None:
        """Update cost set summary with aggregated data - PRESERVE existing data"""
        cost_set = self.cost_set
        cost_lines = cost_set.cost_lines.all()

        total_cost = sum(line.total_cost for line in cost_lines)
        total_rev = sum(line.total_rev for line in cost_lines)
        total_hours = sum(
            float(line.quantity) for line in cost_lines if line.kind == "time"
        )

        # Preserve existing summary data (especially revisions)
        current_summary = cost_set.summary or {}
        current_summary.update(
            {
                "cost": float(total_cost),
                "rev": float(total_rev),
                "hours": total_hours,
            }
        )

        cost_set.summary = current_summary  # Preserves revisions[]
        cost_set.save()

        # Update job.updated_at to ensure ETag changes when cost data changes
        # This prevents 304 Not Modified responses when quotes/costs are modified
        from apps.accounts.models import Staff

        cost_set.job.save(
            staff=Staff.get_automation_user(), update_fields=["updated_at"]
        )

    def save(self, *args, **kwargs):
        # Fail fast if trying to set revenue on shop jobs
        job = self.cost_set.job
        if job.shop_job:
            if self.unit_rev != Decimal("0.00"):
                raise ValidationError(
                    f"Shop jobs cannot have revenue. Got unit_rev={self.unit_rev} "
                    f"for job '{job.name}' (job_number={job.job_number})"
                )
            if self.kind == "time":
                meta = self.meta if isinstance(self.meta, dict) else {}
                if meta.get("is_billable", False):
                    raise ValidationError(
                        f"Shop job time entries cannot be billable. "
                        f"Job '{job.name}' (job_number={job.job_number})"
                    )

        self.full_clean()
        super().save(*args, **kwargs)
        self._update_cost_set_summary()

    def delete(self, *args, **kwargs):
        super().delete(*args, **kwargs)
        self._update_cost_set_summary()
