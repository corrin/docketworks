"""
Serializers for Quote Sync Views.
"""

from rest_framework import serializers

from apps.job.serializers.costing_serializer import CostSetSerializer


class ValidationReportSerializer(serializers.Serializer):
    """Serializer for validation report data."""

    warnings = serializers.ListField(child=serializers.CharField(), required=False)
    errors = serializers.ListField(child=serializers.CharField(), required=False)


class DiffPreviewSerializer(serializers.Serializer):
    """Serializer for a summary of changes in a quote sync."""

    additions_count = serializers.IntegerField()
    updates_count = serializers.IntegerField()
    deletions_count = serializers.IntegerField()
    total_changes = serializers.IntegerField()
    next_revision = serializers.IntegerField(required=False)
    current_revision = serializers.IntegerField(required=False, allow_null=True)


class QuoteSyncErrorResponseSerializer(serializers.Serializer):
    """Serializer for quote sync error responses."""

    error = serializers.CharField()


class LinkQuoteSheetSerializer(serializers.Serializer):
    """Serializer for link quote sheet request data."""

    template_url = serializers.URLField(required=False, allow_null=True)


class LinkQuoteSheetResponseSerializer(serializers.Serializer):
    """Serializer for link quote sheet response."""

    sheet_url = serializers.URLField()
    sheet_id = serializers.CharField()
    job_id = serializers.CharField()


class DraftLineSerializer(serializers.Serializer):
    """Serializer for draft line data."""

    kind = serializers.CharField()
    desc = serializers.CharField()
    quantity = serializers.DecimalField(max_digits=10, decimal_places=2)
    unit_cost = serializers.DecimalField(max_digits=10, decimal_places=2)
    unit_rev = serializers.DecimalField(max_digits=10, decimal_places=2)
    total_cost = serializers.DecimalField(max_digits=10, decimal_places=2)
    total_rev = serializers.DecimalField(max_digits=10, decimal_places=2)


class QuoteChangesSerializer(serializers.Serializer):
    """Serializer for quote changes data."""

    additions = DraftLineSerializer(many=True)
    updates = DraftLineSerializer(many=True)
    deletions = DraftLineSerializer(many=True)


class PreviewQuoteResponseSerializer(serializers.Serializer):
    """Serializer for preview quote response."""

    success = serializers.BooleanField(required=False)
    draft_lines = DraftLineSerializer(many=True, required=False)
    changes = QuoteChangesSerializer(required=False)
    message = serializers.CharField(required=False)
    can_proceed = serializers.BooleanField(default=False)
    validation_report = ValidationReportSerializer(required=False, allow_null=True)
    diff_preview = DiffPreviewSerializer(required=False, allow_null=True)

    # Allow additional fields that might come from the service
    class Meta:
        extra_kwargs = {"allow_extra_fields": True}


class ApplyQuoteResponseSerializer(serializers.Serializer):
    """Serializer for apply quote response."""

    success = serializers.BooleanField()
    cost_set = CostSetSerializer(required=False, allow_null=True)
    draft_lines = DraftLineSerializer(many=True, required=False)
    changes = QuoteChangesSerializer(required=False)
    error = serializers.CharField(required=False)


class ApplyQuoteErrorResponseSerializer(serializers.Serializer):
    """Serializer for apply quote error response."""

    success = serializers.BooleanField(default=False)
    error = serializers.CharField()
