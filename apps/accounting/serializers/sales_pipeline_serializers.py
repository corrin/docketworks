"""Serializers for the Sales Pipeline Report endpoint."""

from typing import Any

from django.utils import timezone
from rest_framework import serializers


class SalesPipelineQuerySerializer(serializers.Serializer[Any]):
    """Validates query params for ``GET /api/accounting/reports/sales-pipeline/``."""

    start_date = serializers.DateField(required=True)
    end_date = serializers.DateField(required=False)
    rolling_window_weeks = serializers.IntegerField(
        required=False, min_value=1, default=4
    )
    trend_weeks = serializers.IntegerField(required=False, min_value=1, default=13)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if attrs.get("end_date") is None:
            attrs["end_date"] = timezone.localdate()
        if attrs["start_date"] > attrs["end_date"]:
            raise serializers.ValidationError(
                {"end_date": "end_date must be on or after start_date."}
            )
        return attrs


class SalesPipelinePeriodSerializer(serializers.Serializer[Any]):
    start_date = serializers.DateField()
    end_date = serializers.DateField()
    rolling_window_weeks = serializers.IntegerField()
    trend_weeks = serializers.IntegerField()
    daily_approved_hours_target = serializers.FloatField()


class SalesPipelineScoreboardSerializer(serializers.Serializer[Any]):
    approved_hours_total = serializers.FloatField()
    approved_jobs_count = serializers.IntegerField()
    direct_hours = serializers.FloatField()
    direct_jobs_count = serializers.IntegerField()
    working_days = serializers.IntegerField()
    target_hours_for_period = serializers.FloatField()
    pace_vs_target = serializers.FloatField(allow_null=True)


class SalesPipelineSnapshotJobSerializer(serializers.Serializer[Any]):
    id = serializers.CharField()
    job_number = serializers.IntegerField()
    name = serializers.CharField()
    client_name = serializers.CharField(allow_blank=True)
    hours = serializers.FloatField()
    value = serializers.FloatField()
    days_in_stage = serializers.IntegerField()


class SalesPipelineStageBucketSerializer(serializers.Serializer[Any]):
    count = serializers.IntegerField()
    hours_total = serializers.FloatField()
    value_total = serializers.FloatField()
    avg_days_in_stage = serializers.FloatField()
    jobs = SalesPipelineSnapshotJobSerializer(many=True)


class SalesPipelineSnapshotSerializer(serializers.Serializer[Any]):
    as_of = serializers.DateField()
    draft = SalesPipelineStageBucketSerializer()
    awaiting_approval = SalesPipelineStageBucketSerializer()


class SalesPipelineVelocityMetricSerializer(serializers.Serializer[Any]):
    median_days = serializers.FloatField(allow_null=True)
    p80_days = serializers.FloatField(allow_null=True)
    sample_size = serializers.IntegerField()


class SalesPipelineVelocitySerializer(serializers.Serializer[Any]):
    draft_to_quote_sent = SalesPipelineVelocityMetricSerializer()
    quote_sent_to_resolved = SalesPipelineVelocityMetricSerializer()
    created_to_approved = SalesPipelineVelocityMetricSerializer()


class SalesPipelineFunnelBucketSerializer(serializers.Serializer[Any]):
    count = serializers.IntegerField()
    hours = serializers.FloatField()


class SalesPipelineFunnelSerializer(serializers.Serializer[Any]):
    accepted = SalesPipelineFunnelBucketSerializer()
    rejected = SalesPipelineFunnelBucketSerializer()
    waiting = SalesPipelineFunnelBucketSerializer()
    direct = SalesPipelineFunnelBucketSerializer()
    still_draft = SalesPipelineFunnelBucketSerializer()


class SalesPipelineTrendWeekSerializer(serializers.Serializer[Any]):
    week_start = serializers.DateField()
    week_end = serializers.DateField()
    approved_hours = serializers.FloatField()
    approved_hours_per_working_day = serializers.FloatField()
    acceptance_rate_by_hours = serializers.FloatField(allow_null=True)
    pipeline_hours_at_week_end = serializers.FloatField()
    median_velocity_days = serializers.FloatField(allow_null=True)
    working_days = serializers.IntegerField()


class SalesPipelineRollingPointSerializer(serializers.Serializer[Any]):
    week_start = serializers.DateField()
    rolling_avg_approved_hours = serializers.FloatField()


class SalesPipelineTrendSerializer(serializers.Serializer[Any]):
    weeks = SalesPipelineTrendWeekSerializer(many=True)
    rolling_average = SalesPipelineRollingPointSerializer(many=True)


class SalesPipelineWarningSampleJobSerializer(serializers.Serializer[Any]):
    id = serializers.CharField()
    job_number = serializers.IntegerField(allow_null=True)
    name = serializers.CharField(allow_blank=True)


class SalesPipelineWarningSerializer(serializers.Serializer[Any]):
    code = serializers.CharField()
    section = serializers.CharField()
    count = serializers.IntegerField()
    sample_jobs = SalesPipelineWarningSampleJobSerializer(many=True)


class SalesPipelineResponseSerializer(serializers.Serializer[Any]):
    """Top-level response for the Sales Pipeline Report."""

    period = SalesPipelinePeriodSerializer()
    scoreboard = SalesPipelineScoreboardSerializer()
    pipeline_snapshot = SalesPipelineSnapshotSerializer()
    velocity = SalesPipelineVelocitySerializer()
    conversion_funnel = SalesPipelineFunnelSerializer()
    trend = SalesPipelineTrendSerializer()
    warnings = SalesPipelineWarningSerializer(many=True)
