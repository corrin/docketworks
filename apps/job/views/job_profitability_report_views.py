"""Views for job profitability reporting."""

import logging

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.job.permissions import IsOfficeStaff
from apps.job.serializers.job_profitability_report_serializers import (
    JobProfitabilityQuerySerializer,
    JobProfitabilityReportResponseSerializer,
)
from apps.job.services.job_profitability_report import JobProfitabilityReportService
from apps.workflow.services.error_persistence import persist_app_error

logger = logging.getLogger(__name__)


class JobProfitabilityReportView(APIView):
    """API view for job profitability reporting."""

    permission_classes = [IsAuthenticated, IsOfficeStaff]

    @extend_schema(
        operation_id="job_profitability_report",
        summary="Job profitability report",
        description="Returns profitability data for completed/archived jobs in a date range.",
        parameters=[
            OpenApiParameter(name="start_date", type=str, required=True),
            OpenApiParameter(name="end_date", type=str, required=True),
            OpenApiParameter(name="min_value", type=str, required=False),
            OpenApiParameter(name="max_value", type=str, required=False),
            OpenApiParameter(name="pricing_type", type=str, required=False),
        ],
        responses={
            200: JobProfitabilityReportResponseSerializer,
            400: dict,
            500: dict,
        },
        tags=["Reports"],
    )
    def get(self, request) -> Response:
        """Generate job profitability report."""
        query_serializer = JobProfitabilityQuerySerializer(data=request.query_params)
        if not query_serializer.is_valid():
            return Response(query_serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        params = query_serializer.validated_data

        try:
            service = JobProfitabilityReportService(
                start_date=params["start_date"],
                end_date=params["end_date"],
                min_value=params.get("min_value"),
                max_value=params.get("max_value"),
                pricing_type=params.get("pricing_type"),
            )
            result = service.generate_report()

            response_serializer = JobProfitabilityReportResponseSerializer(data=result)
            response_serializer.is_valid(raise_exception=True)

            return Response(response_serializer.data, status=status.HTTP_200_OK)
        except Exception as exc:
            logger.error(
                f"Error generating job profitability report: {exc}", exc_info=True
            )
            app_error = persist_app_error(exc)
            return Response(
                {
                    "error": f"Failed to generate job profitability report: {str(exc)}",
                    "error_id": str(app_error.id),
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
