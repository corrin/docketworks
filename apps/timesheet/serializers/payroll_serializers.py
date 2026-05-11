"""
Xero Payroll Serializers

DRF serializers for Xero Payroll API endpoints
"""

from rest_framework import serializers


class CreatePayRunSerializer(serializers.Serializer):
    """Request serializer for creating a pay run"""

    week_start_date = serializers.DateField(help_text="Monday of the week (YYYY-MM-DD)")


class CreatePayRunResponseSerializer(serializers.Serializer):
    """Response serializer for created pay run"""

    id = serializers.UUIDField(help_text="Django primary key")
    xero_id = serializers.UUIDField(help_text="Xero pay run ID")
    status = serializers.CharField()
    period_start_date = serializers.DateField()
    period_end_date = serializers.DateField()
    payment_date = serializers.DateField()
    xero_url = serializers.CharField(help_text="Deep link to pay run in Xero")


class PostWeekToXeroSerializer(serializers.Serializer):
    """Request serializer for posting weekly timesheets to Xero"""

    staff_ids = serializers.ListField(
        child=serializers.UUIDField(),
        help_text="List of staff member UUIDs",
    )
    week_start_date = serializers.DateField(help_text="Monday of the week (YYYY-MM-DD)")


class PostWeekToXeroStartResponseSerializer(serializers.Serializer):
    """Response serializer for starting payroll posting SSE workflow."""

    task_id = serializers.UUIDField(help_text="Server-side task identifier")
    stream_url = serializers.CharField(help_text="SSE endpoint for payroll progress")


class PostWeekToXeroResponseSerializer(serializers.Serializer):
    """Response serializer for posted timesheet"""

    success = serializers.BooleanField()
    xero_timesheet_id = serializers.CharField(allow_null=True)
    xero_leave_ids = serializers.ListField(
        child=serializers.CharField(), allow_null=True, allow_empty=True, required=False
    )
    entries_posted = serializers.IntegerField()
    work_hours = serializers.DecimalField(max_digits=10, decimal_places=2)
    other_leave_hours = serializers.DecimalField(max_digits=10, decimal_places=2)
    leave_hours = serializers.DecimalField(max_digits=10, decimal_places=2)
    errors = serializers.ListField(child=serializers.CharField())


class PayRunListItemSerializer(serializers.Serializer):
    """Serializer for a pay run in the list response."""

    id = serializers.UUIDField(help_text="Django primary key")
    xero_id = serializers.UUIDField(help_text="Xero pay run ID")
    period_start_date = serializers.DateField()
    period_end_date = serializers.DateField()
    payment_date = serializers.DateField()
    pay_run_status = serializers.CharField()
    xero_url = serializers.CharField(help_text="Deep link to pay run in Xero")


class PayRunListResponseSerializer(serializers.Serializer):
    """Response serializer for listing all pay runs."""

    pay_runs = PayRunListItemSerializer(many=True)
    next_postable_week_start_date = serializers.DateField(
        allow_null=True,
        help_text=(
            "Monday of the only payroll week that can currently be posted to "
            "Xero — Xero processes pay runs in sequence (the open Draft's week, "
            "else the week after the latest pay run, else the calendar's anchor "
            "week). Null only if no payroll calendar is configured, in which "
            "case the client should default to the current week."
        ),
    )
    next_postable_week_end_date = serializers.DateField(allow_null=True)


class PayRunSyncResponseSerializer(serializers.Serializer):
    """Response payload after refreshing cached pay runs."""

    synced = serializers.BooleanField()
    fetched = serializers.IntegerField(help_text="Number of pay runs fetched from Xero")
    created = serializers.IntegerField(
        help_text="Number of new pay runs created locally"
    )
    updated = serializers.IntegerField(help_text="Number of existing pay runs updated")
