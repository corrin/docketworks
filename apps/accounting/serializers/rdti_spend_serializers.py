"""
Serializers for RDTI Spend Report API.
"""

from typing import Any

from rest_framework import serializers


class RDTISpendQuerySerializer(serializers.Serializer[Any]):
    """Validates query parameters for the RDTI spend report."""

    start_date = serializers.DateField(required=True)
    end_date = serializers.DateField(required=True)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if attrs["start_date"] > attrs["end_date"]:
            raise serializers.ValidationError("start_date must not be after end_date.")
        return attrs


class RDTISpendCategorySummarySerializer(serializers.Serializer[Any]):
    """Summary data for a single RDTI classification category."""

    rdti_type = serializers.CharField()
    label = serializers.CharField()
    hours = serializers.FloatField()
    cost = serializers.FloatField()
    revenue = serializers.FloatField()
    job_count = serializers.IntegerField()


class RDTISpendJobDetailSerializer(serializers.Serializer[Any]):
    """Per-job detail row in the RDTI spend report."""

    job_id = serializers.CharField()
    job_number = serializers.IntegerField()
    job_name = serializers.CharField()
    client_name = serializers.CharField()
    rdti_type = serializers.CharField()
    hours = serializers.FloatField()
    cost = serializers.FloatField()
    revenue = serializers.FloatField()


class RDTISpendTotalsSerializer(serializers.Serializer[Any]):
    """Grand totals across all RDTI categories."""

    hours = serializers.FloatField()
    cost = serializers.FloatField()
    revenue = serializers.FloatField()


class RDTISpendResponseSerializer(serializers.Serializer[Any]):
    """Top-level response for the RDTI spend report."""

    start_date = serializers.DateField()
    end_date = serializers.DateField()
    summary = RDTISpendCategorySummarySerializer(many=True)
    jobs = RDTISpendJobDetailSerializer(many=True)
    totals = RDTISpendTotalsSerializer()
