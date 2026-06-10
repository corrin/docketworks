import logging
from decimal import Decimal

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.accounts.models import Staff
from apps.job.models import CostLine, CostSet
from apps.job.services.time_entry_rates import (
    calculate_time_unit_rates,
    get_bill_rate_multiplier,
    is_leave_pay_item,
    leave_wage_rate_multiplier,
    normalize_multiplier,
    resolve_xero_pay_item_for_job,
)
from apps.workflow.models import CompanyDefaults

logger = logging.getLogger(__name__)


class CostLineSerializer(serializers.ModelSerializer):
    """
    Serializer for CostLine model - read-only with basic depth
    """

    total_cost = serializers.FloatField(read_only=True)
    total_rev = serializers.FloatField(read_only=True)

    class Meta:
        model = CostLine
        fields = CostLine.COSTLINE_API_FIELDS + ["total_cost", "total_rev"]


class TimesheetCostLineSerializer(serializers.ModelSerializer):
    """
    Serializer for CostLine model specifically for timesheet entries

    Architecture principle: Job data comes from CostSet->Job relationship,
    NOT from metadata. This ensures data consistency and follows SRP:
    - Metadata = timesheet-specific data (staff, date, billable, etc.)
    - Relationship = job data (job_id, job_number, job_name, client)

    Benefits:
    - No data duplication
    - Always consistent with source Job
    - Simplified queries and maintenance
    """

    total_cost = serializers.SerializerMethodField()
    total_rev = serializers.SerializerMethodField()

    # Job information from CostSet relationship (NOT from metadata)
    job_id = serializers.CharField(source="cost_set.job.id", read_only=True)
    job_number = serializers.IntegerField(
        source="cost_set.job.job_number", read_only=True
    )
    job_name = serializers.CharField(source="cost_set.job.name", read_only=True)
    charge_out_rate = serializers.SerializerMethodField()

    # Labour subtype name for display
    labour_subtype_name = serializers.CharField(
        source="labour_subtype.name", read_only=True
    )

    # Client name with null handling
    client_name = serializers.SerializerMethodField()

    # Staff wage rate for frontend cost calculations
    wage_rate = serializers.SerializerMethodField()

    # Xero pay item name for display
    # min_length=1 ensures OpenAPI schema generates minLength: 1
    # Time entries always have xero_pay_item set (validated in CostLine.clean)
    xero_pay_item_name = serializers.CharField(
        source="xero_pay_item.name", read_only=True, min_length=1
    )

    @extend_schema_field(
        serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    )
    def get_charge_out_rate(self, obj: CostLine) -> str:
        """The job's charge-out rate for this line's labour subtype."""
        # Iterate .all() rather than .get() so prefetched labour_rates are used
        for rate in obj.cost_set.job.labour_rates.all():
            if rate.labour_subtype_id == obj.labour_subtype_id:
                # String to match DecimalField JSON rendering
                return str(rate.charge_out_rate)
        raise ValueError(
            f"Job {obj.cost_set.job_id} has no labour rate for subtype "
            f"{obj.labour_subtype_id} (cost line {obj.id})."
        )

    def get_total_cost(self, obj) -> float:
        """Get total cost (quantity * unit_cost)"""
        return float(obj.quantity * obj.unit_cost) if obj.unit_cost else 0.0

    def get_total_rev(self, obj) -> float:
        """Get total revenue (quantity * unit_rev)"""
        return float(obj.quantity * obj.unit_rev) if obj.unit_rev else 0.0

    def get_client_name(self, obj) -> str:
        """Get client name with safe null handling"""
        if obj.cost_set and obj.cost_set.job and obj.cost_set.job.client:
            return obj.cost_set.job.client.name
        return ""

    def get_wage_rate(self, obj) -> float:
        """Get staff wage rate for a time entry."""
        try:
            staff = obj.staff
            if staff is None:
                return 0.0

            return float(staff.wage_rate) if staff.wage_rate else 0.0

        except (Staff.DoesNotExist, ValueError, AttributeError):
            return 0.0

    class Meta:
        model = CostLine
        # COSTLINE_API_FIELDS + timesheet-specific computed fields
        fields = CostLine.COSTLINE_API_FIELDS + [
            "total_cost",
            "total_rev",
            "job_id",
            "job_number",
            "job_name",
            "client_name",
            "charge_out_rate",
            "wage_rate",
            "xero_pay_item_name",
            "labour_subtype_name",
        ]
        read_only_fields = fields


class CostLineCreateUpdateSerializer(serializers.ModelSerializer):
    """
    Serializer for CostLine creation and updates - full write capabilities
    """

    meta = serializers.DictField(required=False, allow_empty=True, default=dict)
    ext_refs = serializers.DictField(required=False, allow_empty=True, default=dict)

    class Meta:
        model = CostLine
        # Write fields - subset of API fields that can be written
        fields = [
            "kind",
            "desc",
            "quantity",
            "unit_cost",
            "unit_rev",
            "accounting_date",
            "ext_refs",
            "meta",
            "created_at",
            "updated_at",
            "xero_pay_item",
            "staff",
            "labour_subtype",
        ]

    def validate(self, data):
        """Custom validation with detailed logging"""
        logger.info(f"Validating CostLine data: {data}")

        # Time lines must carry a labour subtype. Timesheet entries default
        # it from the worker's Staff.default_labour_subtype in save();
        # everything else (estimate/quote editors) must send it explicitly.
        if self.instance is None and data.get("kind") == "time":
            meta = data.get("meta") or {}
            if data.get("labour_subtype") is None and not meta.get(
                "created_from_timesheet"
            ):
                raise serializers.ValidationError(
                    {"labour_subtype": "labour_subtype is required for time lines."}
                )

        return super().validate(data)

    def validate_quantity(self, value):
        """Validate quantity is non-negative"""
        logger.info(f"Validating quantity: {value} (type: {type(value)})")
        if value < 0:
            raise serializers.ValidationError("Quantity must be non-negative")
        return value

    def validate_unit_cost(self, value):
        """Validate unit cost - allow negative values for adjustments"""
        logger.info(f"Validating unit_cost: {value} (type: {type(value)})")
        # Allow negative values for adjustments, discounts, credits
        return value

    def validate_unit_rev(self, value):
        """Validate unit revenue - allow negative values for adjustments"""
        logger.info(f"Validating unit_rev: {value} (type: {type(value)})")
        # Allow negative values for adjustments, discounts, credits
        return value

    def save(self, **kwargs):
        """Override save to auto-calculate unit_cost and unit_rev for timesheet entries"""
        # Check if this is a timesheet entry
        meta = self.validated_data.get("meta", {})
        kind = self.validated_data.get("kind") or getattr(self.instance, "kind", None)

        # A subtype change must reprice the line even when the patch doesn't
        # resend meta (the timesheet UI patches labour_subtype alone). Pull
        # the instance meta so the timesheet recalculation below runs.
        if (
            not meta
            and "labour_subtype" in self.validated_data
            and self.instance is not None
            and (self.instance.meta or {}).get("created_from_timesheet")
        ):
            meta = dict(self.instance.meta)
            self.validated_data["meta"] = meta

        if kind == "time" and meta.get("created_from_timesheet"):
            line_id = self.validated_data.get("id")
            logger.debug(f"Starting to autocalculate unit cost for cost line {line_id}")
            staff_id = meta.get("staff_id")

            if not staff_id:
                exception = serializers.ValidationError(
                    "Staff id must be provided when creating a new timesheet entry."
                )
                raise exception

            try:
                staff = Staff.objects.get(id=staff_id)
                self.validated_data["staff"] = staff
                company_defaults = CompanyDefaults.get_solo()
                cost_set = kwargs.get("cost_set") or getattr(
                    self.instance, "cost_set", None
                )
                if cost_set is None:
                    exception = serializers.ValidationError(
                        "Cost set must be available when saving a timesheet entry."
                    )
                    raise exception
                job = cost_set.job

                # Use staff wage_rate or company default
                wage_rate = (
                    staff.wage_rate if staff.wage_rate else company_defaults.wage_rate
                )

                rate_multiplier_value = meta.get("wage_rate_multiplier")
                if rate_multiplier_value is None:
                    exception = serializers.ValidationError(
                        "Rate multiplier must be provided when creating a new timesheet entry."
                    )
                    raise exception

                labour_subtype = self.validated_data.get("labour_subtype") or getattr(
                    self.instance, "labour_subtype", None
                )
                if labour_subtype is None:
                    labour_subtype = staff.default_labour_subtype
                if labour_subtype is None:
                    raise serializers.ValidationError(
                        "labour_subtype is required for time entries and staff "
                        f"{staff.id} has no default_labour_subtype."
                    )
                self.validated_data["labour_subtype"] = labour_subtype

                wage_rate_multiplier = normalize_multiplier(rate_multiplier_value)
                pay_item = resolve_xero_pay_item_for_job(
                    job=job,
                    wage_rate_multiplier=wage_rate_multiplier,
                )
                if is_leave_pay_item(pay_item):
                    wage_rate_multiplier = leave_wage_rate_multiplier(pay_item)
                    bill_rate_multiplier = Decimal("0.00")
                else:
                    bill_rate_multiplier = get_bill_rate_multiplier(
                        meta, wage_rate_multiplier
                    )
                unit_cost, unit_rev, wage_rate, charge_out_rate = (
                    calculate_time_unit_rates(
                        wage_rate=wage_rate,
                        charge_out_rate=job.labour_rates.get(
                            labour_subtype=labour_subtype
                        ).charge_out_rate,
                        wage_rate_multiplier=wage_rate_multiplier,
                        bill_rate_multiplier=bill_rate_multiplier,
                    )
                )
                self.validated_data["unit_cost"] = unit_cost
                self.validated_data["unit_rev"] = unit_rev
                self.validated_data["xero_pay_item"] = pay_item
                meta["wage_rate_multiplier"] = float(wage_rate_multiplier)
                meta["bill_rate_multiplier"] = float(bill_rate_multiplier)
                meta["is_billable"] = bill_rate_multiplier > Decimal("0.00")
                meta["wage_rate"] = float(wage_rate)
                meta["charge_out_rate"] = float(charge_out_rate)
                self.validated_data["meta"] = meta
                logger.debug(
                    f"Auto-calculated time rates for staff {staff_id}: "
                    f"unit_cost={unit_cost}, unit_rev={unit_rev}"
                )

            except Staff.DoesNotExist:
                raise serializers.ValidationError(f"Staff not found: {staff_id}")
            except Exception as e:
                logger.error(f"Error calculating unit_cost: {e}")
                raise

        return super().save(**kwargs)

    def create(self, validated_data):
        """Override create to define line approval automatically"""
        staff: Staff = self.context["staff"]

        if not staff:
            raise serializers.ValidationError(
                "Missing staff context from request, can't proceed with line approval validation."
            )

        validated_data["approved"] = staff.is_office_staff
        return super().create(validated_data)


class CostSetSummarySerializer(serializers.Serializer):
    """
    Serializer for CostSet summary data - used in cost analysis
    """

    cost = serializers.FloatField(help_text="Total cost for this cost set")
    rev = serializers.FloatField(help_text="Total revenue for this cost set")
    hours = serializers.FloatField(help_text="Total hours for this cost set")
    profitMargin = serializers.SerializerMethodField(
        help_text="Calculated profit margin percentage"
    )

    def get_profitMargin(self, obj) -> float:
        """Calculate profit margin as a percentage"""
        rev = obj.get("rev", 0)
        cost = obj.get("cost", 0)
        if rev > 0:
            return ((rev - cost) / rev) * 100
        return 0.0


class CostSetSerializer(serializers.ModelSerializer):
    """
    Serializer for CostSet model - includes nested cost lines
    """

    cost_lines = CostLineSerializer(many=True, read_only=True)
    summary = CostSetSummarySerializer(read_only=True)
    id = serializers.CharField(read_only=True)  # UUID as string

    def to_representation(self, instance):
        data = super().to_representation(instance)

        # Check for missing summary data - log error but don't crash frontend
        summary = data.get("summary")
        if not summary:
            logger.error(f"CostSet {instance.id} missing required summary data")
            # Return minimal safe structure
            data["summary"] = {"cost": 0, "rev": 0, "hours": 0, "profitMargin": 0.0}
            return data

        # Calculate profit margin
        rev = summary.get("rev", 0)
        cost = summary.get("cost", 0)
        if rev > 0:
            summary["profitMargin"] = ((rev - cost) / rev) * 100
        else:
            summary["profitMargin"] = 0.0

        data["summary"] = summary
        return data

    class Meta:
        model = CostSet
        fields = CostSet.COSTSET_ALL_FIELDS + ["cost_lines"]
        read_only_fields = fields


class CostSetSummaryOnlySerializer(CostSetSerializer):
    """CostSet serializer that includes summary but omits cost lines.

    Subclasses CostSetSerializer so the schema reuses the same component
    (no duplicate enum for the ``kind`` field). Only overrides cost_lines
    to return an empty list.
    """

    cost_lines = serializers.SerializerMethodField()

    def get_cost_lines(self, obj) -> list:
        return []


class CostLineErrorResponseSerializer(serializers.Serializer):
    """Serializer for cost line error responses."""

    error = serializers.CharField()


class CostLineApprovalResponseSerializer(serializers.Serializer):
    """Serializer for non-material cost line approval responses."""

    success = serializers.BooleanField()
    message = serializers.CharField(required=False, allow_blank=True)
    line = CostLineSerializer()


class QuoteImportStatusResponseSerializer(serializers.Serializer):
    """Serializer for quote import status response"""

    job_id = serializers.CharField()
    job_name = serializers.CharField()
    has_quote = serializers.BooleanField()
    quote = CostSetSerializer(required=False)
    revision = serializers.IntegerField(required=False)
    created = serializers.DateTimeField(required=False)
    summary = serializers.JSONField(required=False)


class QuoteRevisionSerializer(serializers.Serializer):
    """Serializer for quote revision request - validates input data"""

    reason = serializers.CharField(
        max_length=500,
        required=False,
        help_text="Optional reason for creating a new quote revision",
    )


class QuoteRevisionResponseSerializer(serializers.Serializer):
    """Serializer for quote revision response"""

    success = serializers.BooleanField()
    message = serializers.CharField()
    quote_revision = serializers.IntegerField()
    archived_cost_lines_count = serializers.IntegerField()
    job_id = serializers.CharField()

    # Optional error details
    error = serializers.CharField(required=False)


class QuoteRevisionsListSerializer(serializers.Serializer):
    """Serializer for listing quote revisions"""

    job_id = serializers.CharField()
    job_number = serializers.IntegerField()
    current_cost_set_rev = serializers.IntegerField()
    total_revisions = serializers.IntegerField()
    revisions = serializers.ListField(
        child=serializers.DictField(),
        help_text="List of archived quote revisions with their data",
    )
