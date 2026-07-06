"""
Data Quality Report Views

REST views for data quality reporting.
Each data quality check has its own endpoint and response structure.
"""

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.company.services.duplicate_phone_report import DuplicatePhoneReportService
from apps.job.permissions import IsOfficeStaff
from apps.job.serializers.data_quality_report_serializers import (
    ArchivedJobsComplianceResponseSerializer,
    DuplicatePhonesResponseSerializer,
)
from apps.job.services.data_quality_report import ArchivedJobsComplianceService
from apps.workflow.exceptions import AlreadyLoggedException
from apps.workflow.services.error_persistence import persist_app_error


class ArchivedJobsComplianceView(APIView):
    """API view for checking archived jobs compliance."""

    permission_classes = [IsAuthenticated, IsOfficeStaff]

    @extend_schema(
        operation_id="check_archived_jobs_compliance",
        summary="Check archived jobs compliance",
        description="Verify that all archived jobs are either cancelled or fully invoiced and paid.",
        responses={
            200: ArchivedJobsComplianceResponseSerializer,
            500: dict,
        },
        tags=["Data Quality"],
    )
    def get(self, request) -> Response:
        """
        Check archived jobs compliance.

        Returns specific compliance information for archived jobs.
        """
        try:
            # Execute the check with the specific service
            service = ArchivedJobsComplianceService()
            result = service.get_compliance_report()

            # Serialize the response with the specific serializer
            serializer = ArchivedJobsComplianceResponseSerializer(data=result)
            serializer.is_valid(raise_exception=True)

            # Return the data directly without wrapping
            return Response(serializer.data, status=status.HTTP_200_OK)
        except AlreadyLoggedException:
            raise  # already persisted upstream — pass through unchanged
        except Exception as exc:
            err = persist_app_error(exc)
            raise AlreadyLoggedException(exc, err.id) from exc


class DuplicatePhonesView(APIView):
    """API view for the duplicate phones data-quality check."""

    permission_classes = [IsAuthenticated, IsOfficeStaff]

    @extend_schema(
        operation_id="check_duplicate_phones",
        summary="Check duplicate phone ownership",
        description=(
            "List phone numbers owned by more than one company, or company numbers "
            "that are actually internal company lines."
        ),
        responses={
            200: DuplicatePhonesResponseSerializer,
            500: dict,
        },
        tags=["Data Quality"],
    )
    def get(self, request: Request) -> Response:
        """Return phone numbers that break the one-number-one-company rule."""
        try:
            result = DuplicatePhoneReportService().get_report()

            serializer = DuplicatePhonesResponseSerializer(data=result)
            serializer.is_valid(raise_exception=True)

            return Response(serializer.data, status=status.HTTP_200_OK)
        except AlreadyLoggedException:
            raise  # already persisted upstream — pass through unchanged
        except Exception as exc:
            err = persist_app_error(exc)
            raise AlreadyLoggedException(exc, err.id) from exc
