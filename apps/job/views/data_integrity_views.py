"""
Data Integrity Report Views

REST views for database integrity checking.
"""

import logging

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.job.permissions import IsOfficeStaff
from apps.job.serializers.data_integrity_serializers import (
    DataIntegrityResponseSerializer,
)
from apps.job.services.data_integrity_service import DataIntegrityService
from apps.workflow.services.error_persistence import persist_app_error

logger = logging.getLogger(__name__)


class DataIntegrityReportView(APIView):
    """API view for comprehensive database integrity checking"""

    permission_classes = [IsAuthenticated, IsOfficeStaff]

    @extend_schema(
        operation_id="scan_data_integrity",
        summary="Scan database integrity",
        description="Check all foreign key relationships, JSON references, and business rules for violations.",
        responses={
            200: DataIntegrityResponseSerializer,
            500: dict,
        },
        tags=["Data Quality"],
    )
    def get(self, request) -> Response:
        """
        Scan database for integrity issues.

        Returns comprehensive report of:
        - Broken FK references
        - Broken JSON field references
        - Business rule violations
        """
        try:
            # Execute the scan
            service = DataIntegrityService()
            result = service.scan_all_relationships()

            # Calculate summary
            result["summary"] = {
                "total_broken_fks": len(result["broken_fk_references"]),
                "total_broken_json_refs": len(result["broken_json_references"]),
                "total_business_rule_violations": len(
                    result["business_rule_violations"]
                ),
                "total_issues": (
                    len(result["broken_fk_references"])
                    + len(result["broken_json_references"])
                    + len(result["business_rule_violations"])
                ),
            }

            # Serialize the response
            serializer = DataIntegrityResponseSerializer(data=result)
            serializer.is_valid(raise_exception=True)

            return Response(serializer.data, status=status.HTTP_200_OK)
        except Exception as exc:
            logger.error(f"Error running data integrity scan: {exc}", exc_info=True)
            app_error = persist_app_error(exc)
            return Response(
                {
                    "error": f"Failed to run data integrity scan: {str(exc)}",
                    "error_id": str(app_error.id),
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
