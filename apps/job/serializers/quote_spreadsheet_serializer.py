"""
Quote Spreadsheet Serializer

Serializer for QuoteSpreadsheet model, providing clean JSON representation
for REST API endpoints.
"""

from rest_framework import serializers

from apps.job.models.spreadsheet import QuoteSpreadsheet
from apps.workflow.serializers_base import NullUnsetModelSerializer


class QuoteSpreadsheetSerializer(NullUnsetModelSerializer[QuoteSpreadsheet]):
    """
    Serializer for QuoteSpreadsheet model.

    Provides clean JSON representation for REST endpoints with
    job information for context.
    """

    job_id = serializers.CharField(source="job.id", read_only=True)
    job_number = serializers.IntegerField(source="job.job_number", read_only=True)
    job_name = serializers.CharField(source="job.name", read_only=True)

    class Meta:
        model = QuoteSpreadsheet
        fields = (
            QuoteSpreadsheet.QUOTESPREADSHEET_API_FIELDS
            + QuoteSpreadsheet.QUOTESPREADSHEET_API_PROPERTIES
        )
        read_only_fields = ["id", "job_id", "job_number", "job_name"]
