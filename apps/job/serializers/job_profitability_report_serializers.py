"""Serializers for job profitability report."""

from rest_framework import serializers


class JobProfitabilityQuerySerializer(serializers.Serializer):
    """Validates query parameters for the profitability report."""

    start_date = serializers.DateField(help_text="Start of date range (inclusive)")
    end_date = serializers.DateField(help_text="End of date range (inclusive)")
    min_value = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        required=False,
        help_text="Minimum job value filter",
    )
    max_value = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        required=False,
        help_text="Maximum job value filter",
    )
    pricing_type = serializers.ChoiceField(
        choices=[
            ("time_materials", "Time & Materials"),
            ("fixed_price", "Fixed Price"),
        ],
        required=False,
        help_text="Filter by pricing methodology",
    )

    def validate(self, data):
        if data["start_date"] > data["end_date"]:
            raise serializers.ValidationError(
                "start_date must be before or equal to end_date"
            )
        min_val = data.get("min_value")
        max_val = data.get("max_value")
        if min_val is not None and max_val is not None and min_val > max_val:
            raise serializers.ValidationError(
                "min_value must be less than or equal to max_value"
            )
        return data


class CostSetMetricsSerializer(serializers.Serializer):
    """Revenue/cost/profit/margin/hours for a single cost set."""

    revenue = serializers.CharField(help_text="Revenue")
    cost = serializers.CharField(help_text="Cost")
    profit = serializers.CharField(help_text="Profit (revenue - cost)")
    margin = serializers.CharField(help_text="Margin %")
    hours = serializers.CharField(help_text="Hours")


class JobProfitabilityItemSerializer(serializers.Serializer):
    """Per-job profitability data."""

    job_id = serializers.CharField(help_text="Job UUID")
    job_number = serializers.IntegerField(help_text="Job number")
    job_name = serializers.CharField(help_text="Job description", allow_blank=True)
    company_name = serializers.CharField(help_text="Company name")
    pricing_type = serializers.CharField(help_text="Pricing methodology key")
    pricing_type_display = serializers.CharField(help_text="Pricing methodology label")
    completion_date = serializers.CharField(
        allow_null=True, help_text="Date job was completed (ISO format)"
    )
    revenue = serializers.CharField(help_text="Job revenue (from invoices)")
    estimate = CostSetMetricsSerializer(help_text="Estimate cost set metrics")
    quote = CostSetMetricsSerializer(help_text="Quote cost set metrics")
    actual = CostSetMetricsSerializer(help_text="Actual cost set metrics")
    profit_variance = serializers.CharField(
        help_text="Actual profit minus baseline profit (quote for FP, estimate for T&M)"
    )
    profit_variance_pct = serializers.CharField(help_text="Variance as % of baseline")


class JobProfitabilitySummarySerializer(serializers.Serializer):
    """Aggregate profitability statistics."""

    total_jobs = serializers.IntegerField(help_text="Total number of jobs in report")
    total_revenue = serializers.CharField(
        help_text="Sum of job revenue (from invoices)"
    )
    total_cost = serializers.CharField(help_text="Sum of actual cost")
    total_profit = serializers.CharField(help_text="Sum of actual profit")
    overall_margin = serializers.CharField(help_text="Overall profit margin %")
    avg_profit_per_job = serializers.CharField(help_text="Average profit per job")
    total_baseline_profit = serializers.CharField(
        help_text="Sum of baseline profit (quote for FP, estimate for T&M)"
    )
    total_variance = serializers.CharField(help_text="Total profit variance")
    tm_jobs = serializers.IntegerField(help_text="Number of T&M jobs")
    fp_jobs = serializers.IntegerField(help_text="Number of fixed price jobs")
    profitable_jobs = serializers.IntegerField(help_text="Jobs with positive profit")
    unprofitable_jobs = serializers.IntegerField(
        help_text="Jobs with zero or negative profit"
    )


class FiltersAppliedSerializer(serializers.Serializer):
    """Echo of the filters that were applied."""

    start_date = serializers.CharField(help_text="Start date ISO string")
    end_date = serializers.CharField(help_text="End date ISO string")
    min_value = serializers.CharField(
        allow_null=True, required=False, help_text="Min value filter"
    )
    max_value = serializers.CharField(
        allow_null=True, required=False, help_text="Max value filter"
    )
    pricing_type = serializers.CharField(
        allow_null=True, required=False, help_text="Pricing type filter"
    )


class JobProfitabilityReportResponseSerializer(serializers.Serializer):
    """Top-level response for the job profitability report."""

    jobs = serializers.ListField(
        child=JobProfitabilityItemSerializer(),
        help_text="List of job profitability rows",
    )
    summary = JobProfitabilitySummarySerializer(
        help_text="Aggregate summary statistics"
    )
    filters_applied = FiltersAppliedSerializer(help_text="Echo of applied filters")
