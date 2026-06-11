from typing import Any

from rest_framework import serializers

from apps.job.models import JobLabourRate, LabourSubtype


class LabourSubtypeSerializer(serializers.ModelSerializer[LabourSubtype]):
    """Read serializer for labour subtypes (dropdowns, rate displays)."""

    class Meta:
        model = LabourSubtype
        fields = [
            "id",
            "name",
            "display_order",
            "is_active",
            "is_workshop",
            "default_charge_out_rate",
        ]
        read_only_fields = fields


class JobLabourRateSerializer(serializers.ModelSerializer[JobLabourRate]):
    """A job's charge-out rate for one labour subtype."""

    labour_subtype_name = serializers.CharField(
        source="labour_subtype.name", read_only=True
    )
    is_workshop = serializers.BooleanField(
        source="labour_subtype.is_workshop", read_only=True
    )

    class Meta:
        model = JobLabourRate
        fields = [
            "id",
            "labour_subtype",
            "labour_subtype_name",
            "is_workshop",
            "charge_out_rate",
        ]
        read_only_fields = [
            "id",
            "labour_subtype",
            "labour_subtype_name",
            "is_workshop",
        ]


class JobLabourRateUpdateSerializer(serializers.Serializer[Any]):
    """One rate change in a job labour-rates update request."""

    labour_subtype = serializers.PrimaryKeyRelatedField(
        queryset=LabourSubtype.objects.all()
    )
    charge_out_rate = serializers.DecimalField(max_digits=10, decimal_places=2)


class JobLabourRatesUpdateRequestSerializer(serializers.Serializer[Any]):
    """Request body for updating a job's labour rates."""

    rates = JobLabourRateUpdateSerializer(many=True, allow_empty=False)
