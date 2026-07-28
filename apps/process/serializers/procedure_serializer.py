"""
Serializers for Procedure (JSA/SWP/SOP) API endpoints.

Document content is stored in Google Docs — these serializers handle
metadata and the Google Doc reference.
"""

from rest_framework import serializers

from apps.process.models import Procedure
from apps.workflow.serializers_base import NullUnsetModelSerializer


class SWPGenerateRequestSerializer(serializers.Serializer):
    """Request serializer for generating a new SWP (standalone)."""

    document_number = serializers.CharField(
        max_length=50,
        required=False,
        allow_blank=True,
        help_text="Document number (e.g., '307' for section 3, doc 7)",
    )
    title = serializers.CharField(
        max_length=255,
        help_text="Name of the safe work procedure",
    )
    description = serializers.CharField(
        help_text="Scope and description of the procedure",
    )
    site_location = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Optional site location for the procedure",
    )


class ProcedureListSerializer(NullUnsetModelSerializer[Procedure]):
    """List serializer for procedure endpoints — includes google_doc_url."""

    job_number = serializers.CharField(
        source="job.job_number", read_only=True, allow_null=True
    )

    class Meta:
        model = Procedure
        fields = [
            "id",
            "document_type",
            "document_number",
            "title",
            "site_location",
            "google_doc_url",
            "job_number",
            "tags",
            "status",
            "created_at",
            "updated_at",
        ]


class ProcedureDetailSerializer(NullUnsetModelSerializer[Procedure]):
    """Detail serializer for procedures — adds google_doc_id, job_id."""

    job_id = serializers.UUIDField(source="job.id", read_only=True, allow_null=True)
    job_number = serializers.CharField(
        source="job.job_number", read_only=True, allow_null=True
    )

    class Meta:
        model = Procedure
        fields = [
            "id",
            "document_type",
            "document_number",
            "title",
            "site_location",
            "google_doc_id",
            "google_doc_url",
            "job_id",
            "job_number",
            "tags",
            "status",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "document_type",
            "created_at",
            "updated_at",
            "google_doc_id",
            "google_doc_url",
        ]


class ProcedureCreateSerializer(serializers.Serializer):
    """Request serializer for creating a blank procedure."""

    title = serializers.CharField(max_length=255)
    document_number = serializers.CharField(
        max_length=50, required=False, allow_blank=True, default=""
    )
    tags = serializers.ListField(
        child=serializers.CharField(), required=False, default=list
    )
    site_location = serializers.CharField(
        max_length=255, required=False, allow_blank=True, default=""
    )


class ProcedureUpdateSerializer(NullUnsetModelSerializer[Procedure]):
    """Update serializer for procedures."""

    class Meta:
        model = Procedure
        fields = [
            "title",
            "document_number",
            "tags",
            "site_location",
            "status",
        ]
        extra_kwargs = {
            "title": {"required": False},
            "document_number": {"required": False},
            "tags": {"required": False},
            "site_location": {"required": False},
            "status": {"required": False},
        }


class ProcessDocumentErrorResponseSerializer(serializers.Serializer):
    """Serializer for error responses."""

    status = serializers.CharField(default="error")
    message = serializers.CharField()
