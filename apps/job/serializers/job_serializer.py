import json
import logging
from typing import Any, Optional

from django.core.exceptions import ObjectDoesNotExist
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.accounting.models.invoice import Invoice
from apps.accounting.models.quote import Quote
from apps.client.models import Client, ClientContact
from apps.job.models import Job, JobEvent, JobFile
from apps.workflow.models import XeroPayItem

from .costing_serializer import (
    CostSetSerializer,
    CostSetSummaryOnlySerializer,
    TimesheetCostLineSerializer,
)
from .job_file_serializer import JobFileSerializer
from .quote_spreadsheet_serializer import QuoteSpreadsheetSerializer

logger = logging.getLogger(__name__)
DEBUG_SERIALIZER = False


class InvoiceSerializer(serializers.ModelSerializer):
    total_excl_tax = serializers.FloatField()
    total_incl_tax = serializers.FloatField()
    amount_due = serializers.FloatField()
    tax = serializers.FloatField(required=False)

    class Meta:
        model = Invoice
        fields = [
            "id",
            "xero_id",
            "number",
            "status",
            "date",
            "due_date",
            "total_excl_tax",
            "total_incl_tax",
            "amount_due",
            "tax",
            "online_url",
        ]


class QuoteSerializer(serializers.ModelSerializer):
    total_excl_tax = serializers.FloatField()
    total_incl_tax = serializers.FloatField()

    class Meta:
        model = Quote
        fields = [
            "id",
            "xero_id",
            "status",
            "date",
            "total_excl_tax",
            "total_incl_tax",
            "online_url",
        ]


# Front-end uses "quote" field with financial data being displayed.
# This is useless for front-end currently, we use all information from above.
# Since I didn't get the specific requirements for this, I'll just ignore and keep using the original serializer.
class XeroQuoteSerializer(serializers.ModelSerializer):
    """Simplified Quote serializer for xero_quote field"""

    class Meta:
        model = Quote
        fields = ["status", "online_url"]


# Same for this.
class XeroInvoiceSerializer(serializers.ModelSerializer):
    """Simplified Invoice serializer for xero_invoices field"""

    class Meta:
        model = Invoice
        fields = ["number", "status", "online_url"]


class CompanyDefaultsJobDetailSerializer(serializers.Serializer):
    """Serializer for company defaults in job detail response"""

    materials_markup = serializers.FloatField(
        help_text="Default markup percentage for materials"
    )
    time_markup = serializers.FloatField(help_text="Default markup percentage for time")
    charge_out_rate = serializers.FloatField(
        help_text="Default charge-out rate for staff"
    )
    wage_rate = serializers.FloatField(help_text="Default wage rate for staff")


class JobSerializer(serializers.ModelSerializer):
    # New CostSet fields (current system)
    latest_estimate = serializers.SerializerMethodField()
    latest_quote = serializers.SerializerMethodField()
    latest_actual = serializers.SerializerMethodField()
    quoted = serializers.BooleanField(read_only=True)
    fully_invoiced = serializers.BooleanField(read_only=True)
    quote = serializers.SerializerMethodField()
    invoices = serializers.SerializerMethodField()

    # CURRENTLY UNUSED/UNUSEFUL FOR FE:
    xero_quote = serializers.SerializerMethodField()
    xero_invoices = serializers.SerializerMethodField()

    client_id = serializers.PrimaryKeyRelatedField(
        queryset=Client.objects.all(),
        source="client",
        write_only=False,  # Allow read access,
        allow_null=True,
        required=False,
    )
    # Some clients might not exist in old production data, so for compatibility we allow null values for it (unrequired, allow_null=True)
    client_name = serializers.CharField(
        source="client.name", read_only=True, allow_null=True, required=False
    )
    contact_id = serializers.PrimaryKeyRelatedField(
        queryset=ClientContact.objects.all(),
        source="contact",
        write_only=False,  # Allow read access
        required=False,
        allow_null=True,
    )
    contact_name = serializers.CharField(
        source="contact.name", read_only=True, required=False, allow_null=True
    )
    default_xero_pay_item_id = serializers.PrimaryKeyRelatedField(
        queryset=XeroPayItem.objects.all(),
        source="default_xero_pay_item",
        write_only=False,
        required=False,
        allow_null=True,
    )
    default_xero_pay_item_name = serializers.CharField(
        source="default_xero_pay_item.name",
        read_only=True,
        required=False,
        allow_null=True,
    )
    job_status = serializers.CharField(source="status")
    job_files = JobFileSerializer(
        source="files", many=True, required=False
    )  # To prevent conflicts with PUTTING only one file

    # Quote spreadsheet relationship
    quote_sheet = QuoteSpreadsheetSerializer(
        read_only=True, required=False, allow_null=True
    )

    @extend_schema_field(CostSetSerializer)
    def get_latest_estimate(self, obj) -> dict | None:
        """Get the latest estimate CostSet"""
        cost_set = obj.get_latest("estimate")
        return CostSetSerializer(cost_set).data if cost_set else None

    @extend_schema_field(CostSetSerializer)
    def get_latest_quote(self, obj) -> dict | None:
        """Get the latest quote CostSet"""
        cost_set = obj.get_latest("quote")
        return CostSetSerializer(cost_set).data if cost_set else None

    @extend_schema_field(CostSetSerializer)
    def get_latest_actual(self, obj) -> dict | None:
        """Get the latest actual CostSet"""
        cost_set = obj.get_latest("actual")
        return CostSetSerializer(cost_set).data if cost_set else None

    @extend_schema_field(QuoteSerializer(allow_null=True))
    def get_quote(self, obj) -> dict | None:
        """Get Xero quote information"""
        try:
            return QuoteSerializer(obj.quote).data
        except ObjectDoesNotExist:
            return None

    @extend_schema_field(InvoiceSerializer(many=True))
    def get_invoices(self, obj) -> list[dict]:
        """Get Xero invoices information"""
        return InvoiceSerializer(obj.invoices.all(), many=True).data

    @extend_schema_field(XeroQuoteSerializer(allow_null=True))
    def get_xero_quote(self, obj) -> dict | None:
        """Get Xero quote information (status and URL only)"""
        try:
            return XeroQuoteSerializer(obj.quote).data
        except ObjectDoesNotExist:
            return None

    @extend_schema_field(XeroInvoiceSerializer(many=True))
    def get_xero_invoices(self, obj) -> list[dict]:
        """Get Xero invoices information (number, status, and URL only)"""
        return XeroInvoiceSerializer(obj.invoices.all(), many=True).data

    class Meta:
        model = Job
        fields = [
            "id",
            "name",
            "client_id",
            "client_name",
            "contact_id",
            "contact_name",
            "job_number",
            "notes",
            "order_number",
            "created_at",
            "updated_at",
            "description",
            # New CostSet fields (current system)
            "latest_estimate",
            "latest_quote",
            "latest_actual",
            "job_status",
            "delivery_date",
            "paid",
            "quote_acceptance_date",
            "job_is_valid",
            "job_files",
            "charge_out_rate",
            "pricing_methodology",
            "price_cap",
            "speed_quality_tradeoff",
            "quote_sheet",
            "quoted",
            "fully_invoiced",
            "quote",
            "invoices",
            "xero_quote",
            "xero_invoices",
            "shop_job",
            "rejected_flag",
            "rdti_type",
            "default_xero_pay_item_id",
            "default_xero_pay_item_name",
        ]

    def validate(self, attrs):
        if DEBUG_SERIALIZER:
            logger.debug(f"JobSerializer validate called with attrs: {attrs}")

        # Validate contact belongs to client
        contact = attrs.get("contact")
        client = attrs.get("client")

        # If we're updating and no client is provided, use the existing client
        if not client and self.instance:
            client = self.instance.client

        if contact and client:
            logger.debug(
                f"JobSerializer validate - Checking if contact {contact.id} belongs to client {client.id}"
            )
            if contact.client != client:
                logger.error(
                    f"JobSerializer validate - Contact {contact.id} does not belong to client {client.id}"
                )
                raise serializers.ValidationError(
                    {
                        "contact_id": f"Contact does not belong to the selected client. Contact belongs to {contact.client.name}, but job is for {client.name}."
                    }
                )
            if DEBUG_SERIALIZER:
                logger.debug(
                    f"JobSerializer validate - Contact {contact.id} belongs to client {client.id}"
                )
                logger.debug("JobSerializer validate - Contact validation passed")

        # No longer validating pricing data - use CostSet/CostLine instead

        validated = super().validate(attrs)
        if DEBUG_SERIALIZER:
            logger.debug(f"After super().validate, data is: {validated}")
        return validated

    def update(self, instance, validated_data):
        # Store original values for change detection
        original_contact = instance.contact if "contact" in validated_data else None

        # Remove read-only/computed fields to avoid AttributeError
        validated_data.pop("quoted", None)
        validated_data.pop("fully_invoiced", None)

        # Handle job files data first
        files_data = validated_data.pop("files", None)
        if files_data:
            existing = {f.id: f for f in instance.files.all()}
            for file_data in files_data:
                file_id = file_data[
                    "id"
                ]  # No need for double validation, DRF ensures this already

                if file_id not in existing:
                    JobFile.objects.create(
                        job=instance,
                        **file_data,
                    )
                    continue

                job_file = existing[file_id]
                serializer = JobFileSerializer(
                    instance=job_file,
                    data=file_data,
                    partial=True,
                    context=self.context,
                )
                serializer.is_valid(raise_exception=True)
                serializer.save()

        # Handle basic job fields - only set and log if actually changed
        for attr, value in validated_data.items():
            # Skip fields that aren't actual Job model fields
            if attr not in [
                "latest_estimate_pricing",
                "latest_quote_pricing",
                "latest_reality_pricing",
                "staff",  # staff comes from request context, not validated_data
            ]:
                # Handle job_status -> status mapping
                target_attr = "status" if attr == "job_status" else attr

                current_value = getattr(instance, target_attr)
                if current_value != value:
                    logger.debug(f"JobSerializer update - Setting {attr} = {value}")
                    setattr(instance, target_attr, value)

        # Get staff from context
        staff = self.context["request"].user if "request" in self.context else None

        # Save the instance
        instance.save(staff=staff)

        # Log contact change after save if it actually changed
        if (
            "contact" in validated_data
            and original_contact != validated_data["contact"]
        ):
            logger.debug(
                f"JobSerializer update - contact changed from {original_contact} to {instance.contact}"
            )

        return instance


class JobQuoteAcceptanceSerializer(serializers.Serializer):
    """Serializer for job quote acceptance data."""

    success = serializers.BooleanField()
    job_id = serializers.UUIDField()
    quote_acceptance_date = serializers.CharField()
    message = serializers.CharField()


class JobEventSerializer(serializers.ModelSerializer):
    """Serializer for JobEvent model - read-only for frontend consumption

    Enhanced to expose complete delta envelope data for undo operations.
    Includes all fields necessary for frontend to implement undo functionality.
    """

    staff = serializers.CharField(
        source="staff.get_display_full_name",
        read_only=True,
        allow_null=True,
        required=False,
    )
    timestamp = serializers.DateTimeField(read_only=True)
    change_id = serializers.UUIDField(read_only=True, allow_null=True)
    schema_version = serializers.IntegerField(read_only=True)
    delta_before = serializers.JSONField(read_only=True, allow_null=True)
    delta_after = serializers.JSONField(read_only=True, allow_null=True)
    delta_meta = serializers.JSONField(read_only=True, allow_null=True)
    delta_checksum = serializers.CharField(read_only=True, allow_blank=True)

    # Enhanced fields for undo support
    can_undo = serializers.SerializerMethodField(
        help_text="Whether this event can be undone"
    )
    undo_description = serializers.SerializerMethodField(
        help_text="Human-readable description of what undoing this event would do"
    )

    def get_can_undo(self, obj) -> bool:
        """Check if this event supports undo operations."""
        return (
            obj.schema_version == 1
            and obj.change_id is not None
            and obj.delta_before is not None
            and obj.delta_after is not None
        )

    def get_undo_description(self, obj) -> str | None:
        """Generate description of what undoing this event would accomplish."""
        if not self.get_can_undo(obj):
            return None

        # Extract field information from delta_meta if available
        meta = obj.delta_meta or {}
        fields = meta.get("fields", [])

        if not fields:
            return f"Undo '{obj.description}'"

        field_names = []
        for field in fields:
            # Map internal field names to user-friendly labels
            field_labels = {
                "name": "job name",
                "description": "description",
                "status": "status",
                "order_number": "order number",
                "notes": "notes",
                "client_id": "client",
                "contact_id": "contact",
                "delivery_date": "delivery date",
                "charge_out_rate": "charge out rate",
                "job_status": "status",
                "paid": "payment status",
                "job_is_valid": "validity",
                "rejected_flag": "rejection status",
                "rdti_type": "RDTI classification",
                "pricing_methodology": "pricing method",
            }
            field_names.append(field_labels.get(field, field.replace("_", " ")))

        if len(field_names) == 1:
            return f"Undo change to {field_names[0]}"
        elif len(field_names) <= 3:
            return (
                f"Undo changes to {', '.join(field_names[:-1])} and {field_names[-1]}"
            )
        else:
            return f"Undo changes to {len(field_names)} fields"

    class Meta:
        model = JobEvent
        fields = JobEvent.JOBEVENT_API_FIELDS + JobEvent.JOBEVENT_API_PROPERTIES
        read_only_fields = fields


class JobDataSerializer(serializers.Serializer):
    job = JobSerializer()
    events = JobEventSerializer(many=True, read_only=True)
    company_defaults = CompanyDefaultsJobDetailSerializer(read_only=True)


class JobSummarySerializer(JobSerializer):
    """Job serializer with cost set summaries only (no cost lines)."""

    @extend_schema_field(CostSetSummaryOnlySerializer)
    def get_latest_estimate(self, obj) -> dict | None:
        cost_set = obj.get_latest("estimate")
        return CostSetSummaryOnlySerializer(cost_set).data if cost_set else None

    @extend_schema_field(CostSetSummaryOnlySerializer)
    def get_latest_quote(self, obj) -> dict | None:
        cost_set = obj.get_latest("quote")
        return CostSetSummaryOnlySerializer(cost_set).data if cost_set else None

    @extend_schema_field(CostSetSummaryOnlySerializer)
    def get_latest_actual(self, obj) -> dict | None:
        cost_set = obj.get_latest("actual")
        return CostSetSummaryOnlySerializer(cost_set).data if cost_set else None


class JobSummaryDataSerializer(serializers.Serializer):
    job = JobSummarySerializer()
    events = JobEventSerializer(many=True, read_only=True)
    company_defaults = CompanyDefaultsJobDetailSerializer(read_only=True)


class JobSummaryResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField(default=True)
    data = JobSummaryDataSerializer()


class CompleteJobSerializer(serializers.ModelSerializer):
    client_name = serializers.CharField(source="client.name", read_only=True)
    job_status = serializers.CharField(source="status")

    class Meta:
        model = Job
        fields = ["id", "job_number", "name", "client_name", "updated_at", "job_status"]


class JobCreateSerializer(serializers.Serializer):
    """Serializer for job creation request data."""

    name = serializers.CharField(max_length=255)
    client_id = serializers.UUIDField()
    description = serializers.CharField(required=False, allow_blank=True)
    order_number = serializers.CharField(required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)
    contact_id = serializers.UUIDField(required=False, allow_null=True)
    pricing_methodology = serializers.CharField(
        required=False, allow_null=True, allow_blank=True
    )
    estimated_materials = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        required=True,
        min_value=0,
        help_text="Estimated material costs in dollars (retail price - what you expect to charge the customer)",
    )
    estimated_time = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        required=True,
        min_value=0,
        help_text="Estimated workshop time in hours",
    )


class JobCreateResponseSerializer(serializers.Serializer):
    """Serializer for job creation response."""

    success = serializers.BooleanField(default=True)
    job_id = serializers.CharField()
    job_number = serializers.IntegerField()
    message = serializers.CharField()


class JobDetailResponseSerializer(serializers.Serializer):
    """Serializer for job detail response."""

    success = serializers.BooleanField(default=True)
    data = JobDataSerializer()


class JobRestErrorResponseSerializer(serializers.Serializer):
    """Serializer for job REST error responses."""

    error = serializers.CharField()


class JobDeleteResponseSerializer(serializers.Serializer):
    """Serializer for job deletion response."""

    success = serializers.BooleanField(default=True)
    message = serializers.CharField()


class AssignJobSerializer(serializers.Serializer):
    """Serialiser for job assignment request (job_id comes from URL)"""

    staff_id = serializers.UUIDField(help_text="Staff ID to assign to the job")


class AssignJobResponseSerializer(serializers.Serializer):
    """Serialiser for job assignment response"""

    success = serializers.BooleanField()
    message = serializers.CharField()


class ArchiveJobsSerializer(serializers.Serializer):
    """Serialiser for job archiving request"""

    ids = serializers.ListField(
        child=serializers.CharField(), help_text="List of job IDs to archive"
    )


class ArchiveJobsResponseSerializer(serializers.Serializer):
    """Serialiser for job archiving response"""

    success = serializers.BooleanField()
    message = serializers.CharField(required=False)
    error = serializers.CharField(required=False)
    errors = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="List of specific errors",
    )


class WorkshopPDFResponseSerializer(serializers.Serializer):
    """Serializer for workshop PDF generation response"""

    # This endpoint returns a PDF file, so we use a simple error response serializer
    status = serializers.CharField(required=False, help_text="Response status")
    message = serializers.CharField(
        required=False, help_text="Error message if applicable"
    )

    class Meta:
        # This is primarily for documentation - the actual response is a
        # FileResponse (PDF)
        help_text = "Generates and returns a workshop PDF for the specified job"


class MonthEndJobHistorySerializer(serializers.Serializer):
    """Serializer for job history in month-end data"""

    date = serializers.DateField()
    total_hours = serializers.FloatField()
    total_dollars = serializers.FloatField()


class MonthEndJobSerializer(serializers.Serializer):
    """Serializer for special jobs in month-end processing"""

    job_id = serializers.UUIDField()
    job_number = serializers.IntegerField()
    job_name = serializers.CharField()
    client_name = serializers.CharField()
    history = MonthEndJobHistorySerializer(many=True)
    total_hours = serializers.FloatField()
    total_dollars = serializers.FloatField()


class MonthEndStockHistorySerializer(serializers.Serializer):
    """Serializer for stock job history in month-end data"""

    date = serializers.DateField()
    material_line_count = serializers.IntegerField()
    material_cost = serializers.FloatField()


class MonthEndStockJobSerializer(serializers.Serializer):
    """Serializer for stock job in month-end processing"""

    job_id = serializers.UUIDField()
    job_number = serializers.IntegerField()
    job_name = serializers.CharField()
    history = MonthEndStockHistorySerializer(many=True)


class MonthEndGetResponseSerializer(serializers.Serializer):
    """Serializer for month-end GET response"""

    jobs = MonthEndJobSerializer(many=True)
    stock_job = MonthEndStockJobSerializer()


class MonthEndPostSerializer(serializers.Serializer):
    """Serializer for month-end POST request"""

    job_ids = serializers.ListField(
        child=serializers.UUIDField(),
        help_text="List of job IDs to process for month-end",
    )


class MonthEndPostResponseSerializer(serializers.Serializer):
    """Serializer for month-end POST response"""

    processed = serializers.ListField(
        child=serializers.UUIDField(),
        help_text="List of successfully processed job IDs",
    )
    errors = serializers.ListField(
        child=serializers.CharField(),
        help_text="List of error messages for failed processing",
    )


class MonthEndErrorResponseSerializer(serializers.Serializer):
    """Serializer for month-end error responses"""

    error = serializers.CharField(help_text="Error message")


# Modern Timesheet Serializers
class ModernTimesheetStaffSerializer(serializers.Serializer):
    """Serializer for staff information in timesheet responses"""

    id = serializers.UUIDField()
    name = serializers.CharField()
    firstName = serializers.CharField()
    lastName = serializers.CharField()


class ModernTimesheetSummarySerializer(serializers.Serializer):
    """Serializer for timesheet entry summary"""

    total_hours = serializers.FloatField()
    billable_hours = serializers.FloatField()
    non_billable_hours = serializers.FloatField()
    total_cost = serializers.FloatField()
    total_revenue = serializers.FloatField()
    entry_count = serializers.IntegerField()
    scheduled_hours = serializers.FloatField()


class ModernTimesheetEntryGetResponseSerializer(serializers.Serializer):
    """Serializer for timesheet entry GET response"""

    cost_lines = TimesheetCostLineSerializer(many=True)
    staff = ModernTimesheetStaffSerializer()
    date = serializers.DateField()
    summary = ModernTimesheetSummarySerializer()


class ModernTimesheetEntryPostSerializer(serializers.Serializer):
    """Serializer for timesheet entry POST request"""

    job_id = serializers.UUIDField()
    staff_id = serializers.UUIDField()
    date = serializers.DateField()
    hours = serializers.FloatField(min_value=0)
    description = serializers.CharField(max_length=500)
    is_billable = serializers.BooleanField(default=True)
    hourly_rate = serializers.FloatField(min_value=0, required=False)
    xero_pay_item_id = serializers.UUIDField()


class ModernTimesheetEntryPostResponseSerializer(serializers.Serializer):
    """Serializer for timesheet entry POST response"""

    success = serializers.BooleanField()
    cost_line_id = serializers.UUIDField(required=False)
    message = serializers.CharField(required=False)


class ModernTimesheetJobGetResponseSerializer(serializers.Serializer):
    """Serializer for timesheet job GET response"""

    jobs = JobSerializer(many=True)
    total_count = serializers.IntegerField()


class ModernTimesheetDayGetResponseSerializer(serializers.Serializer):
    """Serializer for timesheet day GET response"""

    entries = TimesheetCostLineSerializer(many=True)
    summary = ModernTimesheetSummarySerializer()
    date = serializers.DateField()


class ModernTimesheetErrorResponseSerializer(serializers.Serializer):
    """Serializer for timesheet error responses"""

    error = serializers.CharField(help_text="Error message")


class JobEventCreateSerializer(serializers.Serializer):
    """Serializer for job event creation request"""

    description = serializers.CharField(max_length=500)


class JobEventCreateResponseSerializer(serializers.Serializer):
    """Serializer for job event creation response"""

    success = serializers.BooleanField()
    event = JobEventSerializer()


class WeeklyMetricsSerializer(serializers.Serializer):
    """Serializer for weekly metrics data"""

    job_id = serializers.UUIDField()
    job_number = serializers.IntegerField()
    name = serializers.CharField()
    client = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    description = serializers.CharField(
        required=False, allow_null=True, allow_blank=True
    )
    status = serializers.CharField()
    people = serializers.ListField(
        child=serializers.DictField(),
    )
    estimated_hours = serializers.FloatField()
    actual_hours = serializers.FloatField()
    profit = serializers.FloatField()


# JobView Enhancement Serializers


class JobHeaderResponseSerializer(serializers.ModelSerializer):
    """Serializer for job header response - essential job data for fast loading."""

    job_id = serializers.UUIDField(source="id")
    client_id = serializers.UUIDField(
        source="client.id", read_only=True, allow_null=True
    )
    client_name = serializers.CharField(
        source="client.name", read_only=True, allow_null=True
    )
    contact_id = serializers.UUIDField(
        source="contact.id", read_only=True, allow_null=True
    )
    contact_name = serializers.CharField(
        source="contact.name", read_only=True, allow_null=True
    )
    quoted = serializers.BooleanField()
    default_xero_pay_item_id = serializers.UUIDField(
        source="default_xero_pay_item.id", read_only=True, allow_null=True
    )
    default_xero_pay_item_name = serializers.CharField(
        source="default_xero_pay_item.name", read_only=True, allow_null=True
    )

    class Meta:
        model = Job
        # Derive fields from Job.JOB_DIRECT_FIELDS, plus special fields
        fields = [
            "job_id",
            "client_id",
            "client_name",
            "contact_id",
            "contact_name",
            "quoted",
            "default_xero_pay_item_id",
            "default_xero_pay_item_name",
        ] + Job.JOB_DIRECT_FIELDS


class JobStatusChoicesResponseSerializer(serializers.Serializer):
    """Serializer for job status choices response"""

    statuses = serializers.DictField()


class JobInvoicesResponseSerializer(serializers.Serializer):
    """Serializer for job invoices response"""

    invoices = InvoiceSerializer(many=True)


class JobCostSetSummarySerializer(serializers.Serializer):
    """Serializer for cost set summary data in job views"""

    cost = serializers.FloatField()
    rev = serializers.FloatField()
    hours = serializers.FloatField()
    profitMargin = serializers.FloatField(allow_null=True)


class JobCostSummaryResponseSerializer(serializers.Serializer):
    """Serializer for job cost summary response"""

    estimate = JobCostSetSummarySerializer(allow_null=True)
    quote = JobCostSetSummarySerializer(allow_null=True)
    actual = JobCostSetSummarySerializer(allow_null=True)


class JobEventsResponseSerializer(serializers.Serializer):
    """Serializer for job events response"""

    events = JobEventSerializer(many=True)


class JobDeltaRejectionSerializer(serializers.Serializer):
    """Serializer for delta rejection records (read-only)."""

    id = serializers.UUIDField()
    change_id = serializers.UUIDField(allow_null=True)
    job_id = serializers.UUIDField(allow_null=True)
    job_name = serializers.SerializerMethodField()
    reason = serializers.CharField()
    detail = serializers.SerializerMethodField()
    checksum = serializers.CharField(allow_blank=True)
    request_etag = serializers.CharField(allow_blank=True)
    request_ip = serializers.CharField(allow_blank=True, allow_null=True)
    created_at = serializers.DateTimeField()
    envelope = serializers.JSONField()
    staff_id = serializers.UUIDField(allow_null=True)
    staff_email = serializers.SerializerMethodField()

    def get_staff_email(self, obj) -> Optional[str]:
        staff = getattr(obj, "staff", None)
        return getattr(staff, "email", None) if staff else None

    def get_detail(self, obj) -> Any:
        raw = getattr(obj, "detail", "") or ""
        if not raw:
            return None
        try:
            return json.loads(raw)
        except Exception:
            return raw

    def get_job_name(self, obj) -> Optional[str]:
        job = getattr(obj, "job", None)
        return getattr(job, "name", None) if job else None


class JobDeltaRejectionListResponseSerializer(serializers.Serializer):
    """Serializer for paginated delta rejection responses."""

    count = serializers.IntegerField()
    next = serializers.CharField(allow_null=True, required=False)
    previous = serializers.CharField(allow_null=True, required=False)
    results = JobDeltaRejectionSerializer(many=True)


class TimelineEntrySerializer(serializers.Serializer):
    """Serializer for unified timeline entry (JobEvent or CostLine)"""

    id = serializers.UUIDField()
    timestamp = serializers.DateTimeField()
    entry_type = serializers.CharField(
        help_text="Type of entry: 'event', 'costline_created', or 'costline_updated'"
    )
    description = serializers.CharField()
    staff = serializers.CharField(allow_null=True, required=False)
    event_type = serializers.CharField(required=False, allow_null=True)

    # Enhanced fields for undo support (only for event entries)
    can_undo = serializers.SerializerMethodField(
        help_text="Whether this event can be undone (only for event entries)"
    )
    undo_description = serializers.SerializerMethodField(
        help_text="Human-readable description of what undoing this event would do (only for event entries)"
    )

    # JobEvent specific fields for undo functionality (only populated for event entries)
    change_id = serializers.UUIDField(required=False, allow_null=True)
    schema_version = serializers.IntegerField(required=False, allow_null=True)
    delta_before = serializers.JSONField(required=False, allow_null=True)
    delta_after = serializers.JSONField(required=False, allow_null=True)
    delta_meta = serializers.JSONField(required=False, allow_null=True)
    delta_checksum = serializers.CharField(
        required=False, allow_blank=True, allow_null=True
    )

    # CostLine specific fields
    cost_set_kind = serializers.CharField(required=False, allow_null=True)
    costline_kind = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Kind of costline: 'time', 'material', or 'adjust'",
    )
    quantity = serializers.DecimalField(
        max_digits=10, decimal_places=3, required=False, allow_null=True
    )
    unit_cost = serializers.DecimalField(
        max_digits=10, decimal_places=2, required=False, allow_null=True
    )
    unit_rev = serializers.DecimalField(
        max_digits=10, decimal_places=2, required=False, allow_null=True
    )
    total_cost = serializers.DecimalField(
        max_digits=10, decimal_places=2, required=False, allow_null=True
    )
    total_rev = serializers.DecimalField(
        max_digits=10, decimal_places=2, required=False, allow_null=True
    )
    created_at = serializers.DateTimeField(required=False, allow_null=True)
    updated_at = serializers.DateTimeField(required=False, allow_null=True)

    def get_can_undo(self, obj) -> bool | None:
        """Check if this event supports undo operations (only for event entries)."""
        # First check if the value is already calculated in the object
        if "can_undo" in obj:
            return obj["can_undo"]

        if obj.get("entry_type") != "event":
            return None

        # Use the serialized fields directly
        schema_version = obj.get("schema_version")
        change_id = obj.get("change_id")
        delta_before = obj.get("delta_before")
        delta_after = obj.get("delta_after")

        return (
            schema_version == 1
            and change_id is not None
            and delta_before is not None
            and delta_after is not None
        )

    def get_undo_description(self, obj) -> str | None:
        """Generate description of what undoing this event would accomplish (only for event entries)."""
        # First check if the value is already calculated in the object
        if "undo_description" in obj:
            return obj["undo_description"]

        if obj.get("entry_type") != "event" or not self.get_can_undo(obj):
            return None

        # Extract field information from delta_meta if available
        meta = obj.get("delta_meta", {})
        fields = meta.get("fields", [])

        if not fields:
            return f"Undo '{obj.get('description', '')}'"

        field_names = []
        for field in fields:
            # Map internal field names to user-friendly labels
            field_labels = {
                "name": "job name",
                "description": "description",
                "status": "status",
                "order_number": "order number",
                "notes": "notes",
                "client_id": "client",
                "contact_id": "contact",
                "delivery_date": "delivery date",
                "charge_out_rate": "charge out rate",
                "job_status": "status",
                "paid": "payment status",
                "job_is_valid": "validity",
                "rejected_flag": "rejection status",
                "rdti_type": "RDTI classification",
                "pricing_methodology": "pricing method",
            }
            field_names.append(field_labels.get(field, field.replace("_", " ")))

        if len(field_names) == 1:
            return f"Undo change to {field_names[0]}"
        elif len(field_names) <= 3:
            return (
                f"Undo changes to {', '.join(field_names[:-1])} and {field_names[-1]}"
            )
        else:
            return f"Undo changes to {len(field_names)} fields"


class JobTimelineResponseSerializer(serializers.Serializer):
    """Serializer for job timeline response (events + cost lines)"""

    timeline = TimelineEntrySerializer(many=True)


class JobBasicInformationResponseSerializer(serializers.Serializer):
    """Serializer for job basic information response"""

    description = serializers.CharField(allow_blank=True, allow_null=True)
    delivery_date = serializers.DateField(allow_null=True)
    order_number = serializers.CharField(allow_blank=True, allow_null=True)
    notes = serializers.CharField(allow_blank=True, allow_null=True)


class JobPatchSerializer(serializers.Serializer):
    """Serializer for job PATCH request - all updatable fields are optional"""

    # Basic job information
    name = serializers.CharField(
        max_length=100, required=False, allow_blank=False, help_text="Job name"
    )
    description = serializers.CharField(
        required=False, allow_blank=True, allow_null=True, help_text="Job description"
    )
    notes = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text="Internal notes about the job",
    )
    order_number = serializers.CharField(
        max_length=100,
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text="Order number",
    )

    # Status and workflow
    job_status = serializers.ChoiceField(
        choices=Job.JOB_STATUS_CHOICES, required=False, help_text="Job status"
    )
    paid = serializers.BooleanField(
        required=False, help_text="Whether the job has been paid"
    )
    job_is_valid = serializers.BooleanField(
        required=False, help_text="Whether the job is valid"
    )
    rejected_flag = serializers.BooleanField(
        required=False,
        help_text="Whether the job was rejected (quote declined by client)",
    )

    # Dates
    delivery_date = serializers.DateField(
        required=False, allow_null=True, help_text="Delivery date"
    )
    quote_acceptance_date = serializers.DateTimeField(
        required=False, allow_null=True, help_text="Quote acceptance date"
    )

    # Financial
    charge_out_rate = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        required=False,
        allow_null=False,
        help_text="Charge out rate",
    )
    pricing_methodology = serializers.ChoiceField(
        choices=Job.PRICING_METHODOLOGY_CHOICES,
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="Pricing methodology",
    )
    price_cap = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        required=False,
        allow_null=True,
        help_text="Maximum amount to invoice for T&M jobs (do not exceed)",
    )

    # Classification
    rdti_type = serializers.ChoiceField(
        choices=Job.rdti_type.field.choices,
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="R&D Tax Incentive classification",
    )

    # Relationships (only IDs, no derived names)
    client_id = serializers.UUIDField(
        required=False, allow_null=True, help_text="Client ID"
    )
    contact_id = serializers.UUIDField(
        required=False, allow_null=True, help_text="Contact person ID"
    )

    # Files
    job_files = serializers.ListField(
        child=serializers.DictField(), required=False, help_text="Job files"
    )

    def validate_client_id(self, value):
        """Validate that client exists if provided"""
        if value:
            try:
                Client.objects.get(id=value)
            except Client.DoesNotExist:
                raise serializers.ValidationError("Client not found")
        return value

    def validate_contact_id(self, value):
        """Validate that contact exists if provided"""
        if value:
            try:
                ClientContact.objects.get(id=value)
            except ClientContact.DoesNotExist:
                raise serializers.ValidationError("Contact not found")
        return value

    def validate(self, attrs):
        """Cross-field validation"""
        # Validate contact belongs to client if both are provided
        contact_id = attrs.get("contact_id")
        client_id = attrs.get("client_id")

        if contact_id and client_id:
            try:
                contact = ClientContact.objects.get(id=contact_id)
                client = Client.objects.get(id=client_id)
                if contact.client != client:
                    raise serializers.ValidationError(
                        {"contact_id": "Contact does not belong to the selected client"}
                    )
            except (ClientContact.DoesNotExist, Client.DoesNotExist):
                pass  # Individual field validation will catch these

        return attrs


class JobDeltaEnvelopeSerializer(serializers.Serializer):
    """Serializer that validates the delta envelope submitted by the frontend."""

    change_id = serializers.UUIDField()
    actor_id = serializers.UUIDField(required=False, allow_null=True)
    made_at = serializers.DateTimeField(required=False, allow_null=True)
    job_id = serializers.UUIDField(required=False, allow_null=True)
    fields = serializers.ListField(
        child=serializers.CharField(), allow_empty=False, min_length=1
    )
    before = serializers.JSONField()
    after = serializers.JSONField()
    before_checksum = serializers.CharField()
    etag = serializers.CharField(required=False, allow_blank=True, allow_null=True)


class JobUndoSerializer(serializers.Serializer):
    """Request serializer for undoing a job delta."""

    change_id = serializers.UUIDField()
    undo_change_id = serializers.UUIDField(required=False, allow_null=True)
