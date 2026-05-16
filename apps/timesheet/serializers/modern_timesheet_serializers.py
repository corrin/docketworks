"""
Modern Timesheet Serializers

DRF serializers for modern timesheet API endpoints using CostSet/CostLine system
"""

from decimal import Decimal, InvalidOperation

from drf_spectacular.utils import extend_schema_field, extend_schema_serializer
from rest_framework import serializers

from apps.job.models import Job
from apps.timesheet.serializers.daily_timesheet_serializers import (
    SummaryStatsSerializer,
)


class ModernTimesheetJobSerializer(serializers.ModelSerializer):
    """Serializer for jobs in timesheet context using modern CostSet system"""

    client_name = serializers.CharField(
        source="client.name", read_only=True, required=False, allow_null=True
    )
    has_actual_costset = serializers.SerializerMethodField()
    leave_type = serializers.SerializerMethodField()
    estimated_hours = serializers.SerializerMethodField()
    default_xero_pay_item_id = serializers.UUIDField(
        source="default_xero_pay_item.id", read_only=True
    )
    default_xero_pay_item_name = serializers.CharField(
        source="default_xero_pay_item.name", read_only=True
    )
    # Exposed so the timesheet UI can mark new entries non-billable up front
    # (the cost-line validator rejects billable time on shop jobs).
    shop_job = serializers.BooleanField(read_only=True)

    class Meta:
        model = Job
        fields = [
            "id",
            "job_number",
            "name",
            "client_name",
            "status",
            "charge_out_rate",
            "has_actual_costset",
            "leave_type",
            "estimated_hours",
            "default_xero_pay_item_id",
            "default_xero_pay_item_name",
            "shop_job",
        ]

    @extend_schema_field(serializers.BooleanField)
    def get_has_actual_costset(self, obj) -> bool:
        """Check if job has an actual cost set"""
        return obj.get_latest("actual") is not None

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_leave_type(self, obj) -> str | None:
        """Get leave type if this is a payroll leave job"""
        pay_item = obj.default_xero_pay_item
        return pay_item.name if pay_item else None

    @extend_schema_field(serializers.FloatField(allow_null=True))
    def get_estimated_hours(self, obj) -> float | None:
        """Get estimated hours from the latest estimate cost set"""
        estimate = obj.get_latest("estimate")
        if not estimate:
            return None
        summary = estimate.summary
        return summary.get("hours") if summary else None


class ModernStaffSerializer(serializers.Serializer):
    """Serializer for staff in timesheet context"""

    id = serializers.CharField()
    name = serializers.CharField()
    firstName = serializers.CharField()
    lastName = serializers.CharField()
    email = serializers.CharField()
    icon_url = serializers.CharField(allow_null=True, allow_blank=True, required=False)
    wageRate = serializers.DecimalField(max_digits=10, decimal_places=2)


class WeeklySummarySerializer(serializers.Serializer):
    """Serializer for weekly summary data"""

    total_hours = serializers.DecimalField(max_digits=10, decimal_places=2)
    staff_count = serializers.IntegerField()
    billable_percentage = serializers.DecimalField(
        max_digits=5, decimal_places=2, required=False, allow_null=True
    )


class JobMetricsSerializer(serializers.Serializer):
    """Serializer for job metrics in weekly timesheet context"""

    total_estimated_profit = serializers.DecimalField(max_digits=10, decimal_places=2)
    total_actual_profit = serializers.DecimalField(max_digits=10, decimal_places=2)
    total_profit = serializers.DecimalField(max_digits=10, decimal_places=2)


class WeeklyStaffDataWeeklyHoursSerializer(serializers.Serializer):
    """Serializer for weekly hours data of staff with payroll fields"""

    day = serializers.CharField()
    hours = serializers.DecimalField(max_digits=5, decimal_places=2)
    billable_hours = serializers.DecimalField(max_digits=5, decimal_places=2)
    scheduled_hours = serializers.DecimalField(max_digits=5, decimal_places=2)
    status = serializers.CharField()
    leave_type = serializers.CharField(
        allow_blank=True, required=False, allow_null=True
    )
    has_leave = serializers.BooleanField(default=False)

    # Xero Payroll posting categories (only hours that will be posted to Xero)
    billed_hours = serializers.DecimalField(max_digits=10, decimal_places=2)
    unbilled_hours = serializers.DecimalField(max_digits=10, decimal_places=2)
    overtime_1_5x_hours = serializers.DecimalField(max_digits=10, decimal_places=2)
    overtime_2x_hours = serializers.DecimalField(max_digits=10, decimal_places=2)
    sick_leave_hours = serializers.DecimalField(max_digits=10, decimal_places=2)
    annual_leave_hours = serializers.DecimalField(max_digits=10, decimal_places=2)
    bereavement_leave_hours = serializers.DecimalField(max_digits=10, decimal_places=2)
    daily_cost = serializers.DecimalField(max_digits=10, decimal_places=2)
    daily_base_cost = serializers.DecimalField(max_digits=10, decimal_places=2)


class WeeklyStaffDataSerializer(serializers.Serializer):
    """Serializer for staff data in weekly timesheet context with payroll fields"""

    staff_id = serializers.UUIDField()
    name = serializers.CharField()
    weekly_hours = WeeklyStaffDataWeeklyHoursSerializer(many=True)

    total_hours = serializers.DecimalField(max_digits=10, decimal_places=2)
    total_billable_hours = serializers.DecimalField(max_digits=10, decimal_places=2)
    total_scheduled_hours = serializers.DecimalField(max_digits=10, decimal_places=2)
    billable_percentage = serializers.DecimalField(max_digits=5, decimal_places=2)
    status = serializers.CharField()

    # Xero Payroll posting categories (weekly totals, excludes unpaid hours)
    total_billed_hours = serializers.DecimalField(max_digits=10, decimal_places=2)
    total_unbilled_hours = serializers.DecimalField(max_digits=10, decimal_places=2)
    total_overtime_hours = serializers.DecimalField(max_digits=10, decimal_places=2)
    total_overtime_1_5x_hours = serializers.DecimalField(
        max_digits=10, decimal_places=2
    )
    total_overtime_2x_hours = serializers.DecimalField(max_digits=10, decimal_places=2)
    total_sick_leave_hours = serializers.DecimalField(max_digits=10, decimal_places=2)
    total_annual_leave_hours = serializers.DecimalField(max_digits=10, decimal_places=2)
    total_bereavement_leave_hours = serializers.DecimalField(
        max_digits=10, decimal_places=2
    )
    weekly_cost = serializers.DecimalField(max_digits=10, decimal_places=2)
    weekly_base_cost = serializers.DecimalField(max_digits=10, decimal_places=2)


@extend_schema_serializer(component_name="WeeklyTimesheetData")
class WeeklyTimesheetDataSerializer(serializers.Serializer):
    """Serializer for complete weekly timesheet data with payroll fields"""

    start_date = serializers.CharField()
    end_date = serializers.CharField()
    week_days = serializers.ListField(child=serializers.CharField())
    staff_data = WeeklyStaffDataSerializer(many=True)
    weekly_summary = WeeklySummarySerializer()
    job_metrics = JobMetricsSerializer()
    summary_stats = SummaryStatsSerializer()
    export_mode = serializers.CharField()
    is_current_week = serializers.BooleanField()

    # Optional fields added by views
    navigation = serializers.DictField(required=False, allow_null=True)
    weekend_enabled = serializers.BooleanField(required=False)
    week_type = serializers.CharField(required=False, allow_blank=True)


class PaidAbsenceSerializer(serializers.Serializer):
    """Serializer for paid absence request submission"""

    staff_id = serializers.UUIDField()
    start_date = serializers.DateField()
    end_date = serializers.DateField()
    leave_type = serializers.ChoiceField(
        choices=[
            ("annual", "Annual Leave"),
            ("sick", "Sick Leave"),
            ("bereavement", "Bereavement Leave"),
            ("unpaid", "Unpaid Leave"),
        ]
    )
    hours_per_day = serializers.FloatField(min_value=0.1, max_value=24.0)
    description = serializers.CharField(
        required=False, allow_blank=True, max_length=500
    )

    def validate(self, data):
        """Validate that end date is not before start date"""
        if data["end_date"] < data["start_date"]:
            raise serializers.ValidationError("End date cannot be before start date")
        return data


class StaffListResponseSerializer(serializers.Serializer):
    """Serializer for staff list API response"""

    staff = ModernStaffSerializer(many=True)
    total_count = serializers.IntegerField()


class JobsListResponseSerializer(serializers.Serializer):
    """Serializer for jobs list API response"""

    jobs = ModernTimesheetJobSerializer(many=True)
    total_count = serializers.IntegerField()


class WorkshopTimesheetEntrySerializer(serializers.Serializer):
    """Serializer used to expose simplified workshop timesheet entries."""

    id = serializers.UUIDField(read_only=True)
    job_id = serializers.UUIDField(read_only=True)
    job_number = serializers.IntegerField(read_only=True)
    job_name = serializers.CharField(read_only=True)
    client_name = serializers.CharField(read_only=True, allow_blank=True)
    description = serializers.CharField(read_only=True, allow_blank=True)
    hours = serializers.DecimalField(
        max_digits=7, decimal_places=2, read_only=True, source="quantity"
    )
    accounting_date = serializers.DateField(read_only=True)
    start_time = serializers.TimeField(read_only=True, allow_null=True)
    end_time = serializers.TimeField(read_only=True, allow_null=True)
    is_billable = serializers.BooleanField(read_only=True)
    wage_rate_multiplier = serializers.DecimalField(
        max_digits=4, decimal_places=2, read_only=True
    )
    bill_rate_multiplier = serializers.DecimalField(
        max_digits=4, decimal_places=2, read_only=True
    )
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)

    def to_representation(self, instance):
        job = getattr(getattr(instance, "cost_set", None), "job", None)
        meta = instance.meta or {}
        raw_multiplier = meta.get("wage_rate_multiplier", 1.0)
        try:
            rate_multiplier = Decimal(str(raw_multiplier))
        except (InvalidOperation, TypeError):
            rate_multiplier = Decimal("1.0")
        raw_bill_multiplier = meta.get("bill_rate_multiplier")
        try:
            bill_rate_multiplier = (
                Decimal(str(raw_bill_multiplier))
                if raw_bill_multiplier is not None
                else (
                    Decimal("0.0")
                    if meta.get("is_billable") is False
                    else rate_multiplier
                )
            )
        except (InvalidOperation, TypeError):
            bill_rate_multiplier = rate_multiplier

        return {
            "id": str(instance.id),
            "job_id": str(job.id) if job else None,
            "job_number": job.job_number if job else None,
            "job_name": job.name if job else "",
            "client_name": job.client.name if job and job.client else "",
            "description": instance.desc or "",
            "hours": float(instance.quantity),
            "accounting_date": instance.accounting_date,
            "start_time": meta.get("start_time"),
            "end_time": meta.get("end_time"),
            "is_billable": bool(meta.get("is_billable", True)),
            "wage_rate_multiplier": float(rate_multiplier),
            "bill_rate_multiplier": float(bill_rate_multiplier),
            "entry_seq": instance.entry_seq,
            "created_at": instance.created_at,
            "updated_at": instance.updated_at,
        }


class WorkshopTimesheetEntryRequestSerializer(serializers.Serializer):
    """Serializer validating workshop timesheet create requests."""

    job_id = serializers.UUIDField()
    accounting_date = serializers.DateField()
    hours = serializers.DecimalField(
        max_digits=7, decimal_places=2, min_value=Decimal("0.01")
    )
    description = serializers.CharField(
        required=False, allow_blank=True, allow_null=True, max_length=255
    )
    start_time = serializers.TimeField(required=False, allow_null=True)
    end_time = serializers.TimeField(required=False, allow_null=True)
    is_billable = serializers.BooleanField(required=False, default=True)
    wage_rate_multiplier = serializers.DecimalField(
        max_digits=4,
        decimal_places=2,
        required=False,
        min_value=Decimal("0.0"),
        default=Decimal("1.0"),
    )
    bill_rate_multiplier = serializers.DecimalField(
        max_digits=4,
        decimal_places=2,
        required=False,
        min_value=Decimal("0.0"),
    )

    def validate(self, attrs):
        if "bill_rate_multiplier" not in attrs:
            if attrs.get("is_billable", True):
                attrs["bill_rate_multiplier"] = attrs.get(
                    "wage_rate_multiplier", Decimal("1.0")
                )
            else:
                attrs["bill_rate_multiplier"] = Decimal("0.0")
        return attrs


class WorkshopTimesheetEntryUpdateSerializer(serializers.Serializer):
    """Serializer validating workshop timesheet update (PATCH) requests."""

    entry_id = serializers.UUIDField()
    job_id = serializers.UUIDField(required=False)
    accounting_date = serializers.DateField(required=False)
    hours = serializers.DecimalField(
        max_digits=7,
        decimal_places=2,
        min_value=Decimal("0.01"),
        required=False,
    )
    description = serializers.CharField(
        required=False, allow_blank=True, allow_null=True, max_length=255
    )
    start_time = serializers.TimeField(required=False, allow_null=True)
    end_time = serializers.TimeField(required=False, allow_null=True)
    is_billable = serializers.BooleanField(required=False)
    wage_rate_multiplier = serializers.DecimalField(
        max_digits=4, decimal_places=2, required=False, min_value=Decimal("0.0")
    )
    bill_rate_multiplier = serializers.DecimalField(
        max_digits=4, decimal_places=2, required=False, min_value=Decimal("0.0")
    )

    def validate(self, attrs):
        if len(attrs.keys()) <= 1:
            raise serializers.ValidationError(
                "At least one field besides entry_id must be provided."
            )
        return attrs


class WorkshopTimesheetSummarySerializer(serializers.Serializer):
    """Serializer for the aggregated summary in workshop timesheets."""

    total_hours = serializers.FloatField()
    billable_hours = serializers.FloatField()
    non_billable_hours = serializers.FloatField()
    total_cost = serializers.FloatField()
    total_revenue = serializers.FloatField()


class WorkshopTimesheetListResponseSerializer(serializers.Serializer):
    """Serializer describing the GET response payload for workshop timesheets."""

    date = serializers.DateField()
    entries = WorkshopTimesheetEntrySerializer(many=True)
    summary = WorkshopTimesheetSummarySerializer()


class WorkshopTimesheetDeleteRequestSerializer(serializers.Serializer):
    """Serializer validating delete requests for workshop timesheets."""

    entry_id = serializers.UUIDField()
