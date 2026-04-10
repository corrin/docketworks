from typing import Any

from rest_framework import serializers


class WIPQuerySerializer(serializers.Serializer[Any]):
    """Validates query parameters for the WIP report endpoint."""

    date = serializers.DateField(
        required=False, help_text="Report date (YYYY-MM-DD). Defaults to today."
    )
    method = serializers.ChoiceField(
        choices=["revenue", "cost"],
        default="revenue",
        required=False,
        help_text="Valuation method: 'revenue' (charge-out) or 'cost'.",
    )


class WIPJobSerializer(serializers.Serializer[Any]):
    """A single job row in the WIP report."""

    job_number = serializers.IntegerField()
    name = serializers.CharField()
    client = serializers.CharField()
    status = serializers.CharField()
    time_cost = serializers.FloatField()
    time_rev = serializers.FloatField()
    material_cost = serializers.FloatField()
    material_rev = serializers.FloatField()
    adjust_cost = serializers.FloatField()
    adjust_rev = serializers.FloatField()
    total_cost = serializers.FloatField()
    total_rev = serializers.FloatField()
    invoiced = serializers.FloatField()
    gross_wip = serializers.FloatField()
    net_wip = serializers.FloatField()


class WIPStatusBreakdownSerializer(serializers.Serializer[Any]):
    """Breakdown of WIP by job status."""

    status = serializers.CharField()
    count = serializers.IntegerField()
    net_wip = serializers.FloatField()


class WIPSummarySerializer(serializers.Serializer[Any]):
    """Summary totals for the WIP report."""

    job_count = serializers.IntegerField()
    total_gross = serializers.FloatField()
    total_invoiced = serializers.FloatField()
    total_net = serializers.FloatField()
    by_status = WIPStatusBreakdownSerializer(many=True)


class WIPResponseSerializer(serializers.Serializer[Any]):
    """Top-level response for the WIP report."""

    jobs = WIPJobSerializer(many=True)
    archived_jobs = WIPJobSerializer(many=True)
    summary = WIPSummarySerializer()
    report_date = serializers.CharField()
    method = serializers.CharField()
