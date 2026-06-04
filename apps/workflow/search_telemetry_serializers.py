from rest_framework import serializers

from apps.workflow.models import SearchTelemetryEvent


class SearchTelemetryClickRequestSerializer(serializers.Serializer):
    """Generic search result selection telemetry."""

    domain = serializers.ChoiceField(choices=SearchTelemetryEvent.Domain.choices)
    query = serializers.CharField(
        max_length=255, allow_blank=True, trim_whitespace=True
    )
    selected_result_id = serializers.CharField(max_length=255)
    selected_label = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
        default="",
        trim_whitespace=True,
    )
    selected_rank = serializers.IntegerField(
        required=False, allow_null=True, min_value=1
    )
    result_count = serializers.IntegerField(required=False, min_value=0, default=0)
    source = serializers.CharField(
        max_length=100,
        required=False,
        allow_blank=True,
        default="",
        trim_whitespace=True,
    )
    filters = serializers.JSONField(required=False, default=dict)
    metadata = serializers.JSONField(required=False, default=dict)


class SearchTelemetryClickResponseSerializer(serializers.Serializer):
    """Acknowledgement for generic search result selection telemetry."""

    success = serializers.BooleanField()
