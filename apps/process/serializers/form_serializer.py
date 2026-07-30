"""
Serializers for Form and FormEntry API endpoints.

Forms are structured entry documents (checklists, registers, logs).
No Google Doc — data is stored as FormEntry rows.
"""

from rest_framework import serializers

from apps.process.models import Form, FormEntry
from apps.workflow.serializers_base import NullUnsetModelSerializer


class FormEntrySerializer(NullUnsetModelSerializer[FormEntry]):
    """Serializer for FormEntry — filled-in instances of forms."""

    staff_name = serializers.CharField(
        source="staff.get_display_name",
        read_only=True,
        allow_null=True,
    )
    entered_by_name = serializers.CharField(
        source="entered_by.get_display_name",
        read_only=True,
        allow_null=True,
    )
    job_number = serializers.CharField(
        source="job.job_number",
        read_only=True,
        allow_null=True,
    )

    class Meta:
        model = FormEntry
        fields = [
            "id",
            "form",
            "job",
            "job_number",
            "staff",
            "staff_name",
            "entry_date",
            "entered_by",
            "entered_by_name",
            "data",
            "created_at",
        ]
        read_only_fields = ["id", "form", "entered_by", "created_at"]


class FormListSerializer(NullUnsetModelSerializer[Form]):
    """List serializer for form endpoints — includes form_schema."""

    entry_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Form
        fields = [
            "id",
            "document_type",
            "document_number",
            "title",
            "tags",
            "status",
            "form_schema",
            "entry_count",
            "created_at",
            "updated_at",
        ]


class FormDetailSerializer(NullUnsetModelSerializer[Form]):
    """Detail serializer for forms."""

    class Meta:
        model = Form
        fields = [
            "id",
            "document_type",
            "document_number",
            "title",
            "tags",
            "status",
            "form_schema",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "document_type",
            "created_at",
            "updated_at",
        ]


class FormCreateSerializer(serializers.Serializer):
    """Request serializer for creating a form document (no Google Doc)."""

    title = serializers.CharField(max_length=255)
    document_number = serializers.CharField(
        max_length=50, required=False, allow_blank=True, default=""
    )
    tags = serializers.ListField(
        child=serializers.CharField(), required=False, default=list
    )
    form_schema = serializers.JSONField(required=False, default=dict)


class FormUpdateSerializer(NullUnsetModelSerializer[Form]):
    """Update serializer for forms."""

    class Meta:
        model = Form
        fields = [
            "title",
            "document_number",
            "tags",
            "form_schema",
            "status",
        ]
        extra_kwargs = {
            "title": {"required": False},
            "document_number": {"required": False},
            "tags": {"required": False},
            "form_schema": {"required": False},
            "status": {"required": False},
        }
