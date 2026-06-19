from decimal import Decimal
from typing import Any

from rest_framework import serializers

from apps.job.models import JobLabourRate, LabourSubtype


class LabourSubtypeSerializer(serializers.ModelSerializer[LabourSubtype]):
    """Read serializer for labour subtypes (dropdowns, rate displays)."""

    default_charge_out_rate = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=Decimal("0"),
        read_only=True,
        help_text="Company-level rate used to seed JobLabourRate on new jobs",
    )

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


class LabourSubtypeManageSerializer(serializers.ModelSerializer[LabourSubtype]):
    """Read/write serializer for the company labour-subtype management UI."""

    default_charge_out_rate = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=Decimal("0"),
        help_text="Company-level rate used to seed JobLabourRate on new jobs",
    )

    class Meta:
        model = LabourSubtype
        fields = [
            "id",
            "name",
            "display_order",
            "is_active",
            "is_workshop",
            "counts_for_scheduling",
            "default_charge_out_rate",
        ]
        read_only_fields = ["id"]

    def update(
        self, instance: LabourSubtype, validated_data: dict[str, Any]
    ) -> LabourSubtype:
        # Guard: a subtype that is a staff member's default cannot be
        # deactivated — their new timesheet lines resolve via that default and
        # would silently use a subtype no longer offered for entry.
        deactivating = instance.is_active and validated_data.get("is_active") is False
        if deactivating:
            from apps.accounts.models import Staff

            dependent = Staff.objects.filter(default_labour_subtype=instance).count()
            if dependent:
                raise serializers.ValidationError(
                    {
                        "is_active": (
                            f"{dependent} staff default to '{instance.name}'; "
                            "reassign them before deactivating it."
                        )
                    }
                )
        return super().update(instance, validated_data)


class JobLabourRateSerializer(serializers.ModelSerializer[JobLabourRate]):
    """A job's charge-out rate for one labour subtype."""

    charge_out_rate = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=Decimal("0"),
        read_only=True,
    )
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
    charge_out_rate = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=Decimal("0"),
    )


class JobLabourRatesUpdateRequestSerializer(serializers.Serializer[Any]):
    """Request body for updating a job's labour rates."""

    rates = JobLabourRateUpdateSerializer(many=True, allow_empty=False)
