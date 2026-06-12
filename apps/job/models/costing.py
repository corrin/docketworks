import logging
import uuid
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import connection, models, transaction
from django.db.models import Q
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
        - staff_id (str, UUID): Legacy Staff reference; use staff FK instead
        - date (str, ISO date): Date the work was performed (legacy, use accounting_date field)
        - is_billable (bool): Whether this time is billable to the client
        - start_time (str, ISO time): Start time of the timesheet entry
        - end_time (str, ISO time): End time of the timesheet entry
        - wage_rate_multiplier (float): Multiplier for staff wage rate (e.g., 1.5 for overtime)
        - bill_rate_multiplier (float): Multiplier for customer bill rate
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
        "staff",
        "entry_seq",
        "labour_subtype",
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

    staff = models.ForeignKey(
        "accounts.Staff",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="cost_lines",
        help_text="Staff member for actual time entries.",
    )

    # Sequence number - auto-assigned within (staff, accounting_date) for actual time entries
    entry_seq = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Sequence number within a staff member's daily actual time entries.",
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

    # Labour subtype - required for time lines, null for material/adjust
    labour_subtype = models.ForeignKey(
        "job.LabourSubtype",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="cost_lines",
        help_text="The labour subtype for time lines (Workshop, Admin, Onsite, ...)",
    )

    class Meta:
        indexes = [
            models.Index(fields=["cost_set_id", "kind"]),
            models.Index(fields=["cost_set_id", "created_at"]),
            models.Index(fields=["cost_set_id", "kind", "created_at"]),
            models.Index(fields=["staff", "accounting_date", "entry_seq"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["staff", "accounting_date", "entry_seq"],
                condition=Q(
                    kind="time",
                    staff__isnull=False,
                    entry_seq__isnull=False,
                ),
                name="unique_time_entry_staff_day_seq",
            ),
            models.CheckConstraint(
                condition=(
                    Q(staff__isnull=True, entry_seq__isnull=True)
                    | Q(staff__isnull=False, entry_seq__isnull=False)
                ),
                name="costline_staff_entry_seq_pair",
            ),
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

        if self.kind == "time" and self.cost_set.kind == "actual":
            if self.staff_id is None:
                raise ValidationError("Actual time entries must have staff set.")
            if self.entry_seq is None:
                raise ValidationError("Actual time entries must have entry_seq set.")

        if self.kind == "time" and self.labour_subtype_id is None:
            raise ValidationError("Time lines must have labour_subtype set.")
        if self.kind != "time" and self.labour_subtype_id is not None:
            raise ValidationError("Only time lines may have labour_subtype set.")

        validate_costline_meta(self.meta, self.kind)
        validate_costline_ext_refs(self.ext_refs)

    def _actual_time_entry_requires_sequence(self) -> bool:
        if self.kind != "time":
            return False
        if self.cost_set_id is None:
            return False
        return self.cost_set.kind == "actual"

    def _set_staff_from_legacy_meta(self) -> None:
        if self.staff_id is not None:
            return
        if not isinstance(self.meta, dict):
            return
        legacy_staff_id = self.meta.get("staff_id")
        if legacy_staff_id:
            self.staff_id = legacy_staff_id

    def _sequence_group_changed(self) -> bool:
        if self._state.adding or self.pk is None:
            return True
        previous = CostLine.objects.only("staff_id", "accounting_date").get(pk=self.pk)
        return (
            previous.staff_id != self.staff_id
            or previous.accounting_date != self.accounting_date
        )

    def _lock_sequence_group(self) -> None:
        if connection.vendor != "postgresql":
            return
        lock_key = f"costline-entry-seq:{self.staff_id}:{self.accounting_date}"
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", [lock_key])

    def _assign_entry_seq(self) -> None:
        if not self._actual_time_entry_requires_sequence():
            return

        self._set_staff_from_legacy_meta()
        if self.staff_id is None:
            return

        should_assign = self.entry_seq is None or self._sequence_group_changed()
        if not should_assign:
            return

        self._lock_sequence_group()
        previous_max = (
            CostLine.objects.filter(
                kind="time",
                staff_id=self.staff_id,
                accounting_date=self.accounting_date,
                entry_seq__isnull=False,
            )
            .exclude(pk=self.pk)
            .aggregate(max_seq=models.Max("entry_seq"))["max_seq"]
        )
        self.entry_seq = (previous_max or 0) + 1

    @staticmethod
    def _with_sequence_update_fields(
        update_fields, *, requires_sequence: bool, staff_newly_set: bool
    ):
        if update_fields is None:
            return None
        fields = set(update_fields)
        if requires_sequence:
            fields.add("entry_seq")
        if staff_newly_set:
            fields.add("staff")
        return fields

    def _update_cost_set_summary(self) -> None:
        """Update cost set summary with aggregated data - PRESERVE existing data"""
        cost_set_id = self.cost_set_id
        cost_set = CostSet.objects.only("id", "job_id", "summary").get(id=cost_set_id)
        cost_lines = CostLine.objects.filter(cost_set_id=cost_set_id)

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

        CostSet.objects.filter(id=cost_set_id).update(summary=current_summary)

        # Bump job.updated_at via QuerySet.update() so the ETag invalidates
        # without routing through Job.save() — this is a cascade side-effect
        # of a CostLine write, not an attributable action.
        job_model = cost_set._meta.get_field("job").remote_field.model
        job_model.objects.filter(pk=cost_set.job_id).update(updated_at=timezone.now())

    def save(self, *args, **kwargs):
        staff_was_already_set = self.staff_id is not None
        requires_sequence = self._actual_time_entry_requires_sequence()
        with transaction.atomic():
            self._assign_entry_seq()
            staff_newly_set_from_legacy_meta = (
                self.staff_id is not None and not staff_was_already_set
            )
            kwargs["update_fields"] = self._with_sequence_update_fields(
                kwargs.get("update_fields"),
                requires_sequence=requires_sequence,
                staff_newly_set=staff_newly_set_from_legacy_meta,
            )

            self._save_with_summary_update(*args, **kwargs)

    def _save_with_summary_update(self, *args, **kwargs):
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
