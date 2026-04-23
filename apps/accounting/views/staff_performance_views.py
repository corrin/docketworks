from datetime import datetime
from logging import getLogger
from typing import Any

from django.views.generic import TemplateView
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounting.serializers import (
    StaffPerformanceErrorResponseSerializer,
    StaffPerformanceResponseSerializer,
)
from apps.accounting.services import StaffPerformanceService
from apps.workflow.exceptions import AlreadyLoggedException
from apps.workflow.services.error_persistence import persist_app_error

logger = getLogger(__name__)


def _build_staff_error_response(
    *, message: str, status_code: int, details: dict[str, Any] | None = None
) -> Response:
    payload: dict[str, Any] = {"error": message}
    if details is not None:
        payload["details"] = details

    serializer = StaffPerformanceErrorResponseSerializer(data=payload)
    serializer.is_valid(raise_exception=True)
    return Response(serializer.data, status=status_code)


class StaffPerformanceTemplateView(TemplateView):
    """View for rendering the Staff Performance page"""

    template_name = "reports/staff_performance.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Staff Performance Report"
        return context


class StaffPerformanceSummaryAPIView(APIView):
    """API endpoint for staff performance summary (all staff)"""

    serializer_class = StaffPerformanceResponseSerializer

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="start_date",
                type=str,
                required=True,
                description="Start date (YYYY-MM-DD)",
            ),
            OpenApiParameter(
                name="end_date",
                type=str,
                required=True,
                description="End date (YYYY-MM-DD)",
            ),
        ],
        responses={200: StaffPerformanceResponseSerializer},
    )
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        start_date_str = request.query_params.get("start_date")
        end_date_str = request.query_params.get("end_date")

        try:
            # Validate query parameters
            if not start_date_str or not end_date_str:
                error_data = {
                    "error": (
                        "Both start_date and end_date query parameters are required"
                    )
                }
                error_serializer = StaffPerformanceErrorResponseSerializer(
                    data=error_data
                )
                error_serializer.is_valid(raise_exception=True)
                return Response(
                    error_serializer.data, status=status.HTTP_400_BAD_REQUEST
                )

            try:
                start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
                end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
            except ValueError:
                error_data = {"error": "Invalid date format. Use YYYY-MM-DD format"}
                return _build_staff_error_response(
                    message=error_data["error"],
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            if start_date > end_date:
                error_data = {"error": "start_date must be before or equal to end_date"}
                return _build_staff_error_response(
                    message=error_data["error"],
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            # Get staff performance data
            performance_data = StaffPerformanceService.get_staff_performance_data(
                start_date=start_date, end_date=end_date
            )

            # Serialize and return response
            response_serializer = StaffPerformanceResponseSerializer(
                data=performance_data
            )
            response_serializer.is_valid(raise_exception=True)

            return Response(response_serializer.data, status=status.HTTP_200_OK)

        except AlreadyLoggedException as exc:
            logger.error("Error in staff performance summary API: %s", exc.original)
            return _build_staff_error_response(
                message=(
                    "Internal server error occurred while generating staff "
                    "performance report"
                ),
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        except Exception as exc:
            logger.error(f"Error in staff performance summary API: {str(exc)}")
            app_error = persist_app_error(
                exc,
                additional_context={
                    "operation": "staff_performance_summary",
                    "start_date": start_date_str,
                    "end_date": end_date_str,
                },
            )
            return _build_staff_error_response(
                message=(
                    "Internal server error occurred while generating staff "
                    "performance report"
                ),
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                details={"error_id": str(app_error.id)},
            )


class StaffPerformanceDetailAPIView(APIView):
    """API endpoint for individual staff performance detail"""

    serializer_class = StaffPerformanceResponseSerializer

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="start_date",
                type=str,
                required=True,
                description="Start date (YYYY-MM-DD)",
            ),
            OpenApiParameter(
                name="end_date",
                type=str,
                required=True,
                description="End date (YYYY-MM-DD)",
            ),
        ],
        responses={200: StaffPerformanceResponseSerializer},
    )
    def get(
        self, request: Request, staff_id: str, *args: Any, **kwargs: Any
    ) -> Response:
        start_date_str = request.query_params.get("start_date")
        end_date_str = request.query_params.get("end_date")

        try:
            # Validate query parameters
            if not start_date_str or not end_date_str:
                error_data = {
                    "error": (
                        "Both start_date and end_date query parameters are required"
                    )
                }
                error_serializer = StaffPerformanceErrorResponseSerializer(
                    data=error_data
                )
                error_serializer.is_valid(raise_exception=True)
                return Response(
                    error_serializer.data, status=status.HTTP_400_BAD_REQUEST
                )

            try:
                start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
                end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
            except ValueError:
                error_data = {"error": "Invalid date format. Use YYYY-MM-DD format"}
                return _build_staff_error_response(
                    message=error_data["error"],
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            if start_date > end_date:
                error_data = {"error": "start_date must be before or equal to end_date"}
                return _build_staff_error_response(
                    message=error_data["error"],
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            # Get individual staff performance data with job breakdown
            performance_data = StaffPerformanceService.get_staff_performance_data(
                start_date=start_date, end_date=end_date, staff_id=staff_id
            )

            # Check if staff was found
            if not performance_data["staff"]:
                error_data = {
                    "error": f"No performance data found for staff ID: {staff_id}"
                }
                error_serializer = StaffPerformanceErrorResponseSerializer(
                    data=error_data
                )
                error_serializer.is_valid(raise_exception=True)
                return Response(error_serializer.data, status=status.HTTP_404_NOT_FOUND)

            # Serialize and return response
            response_serializer = StaffPerformanceResponseSerializer(
                data=performance_data
            )
            response_serializer.is_valid(raise_exception=True)

            return Response(response_serializer.data, status=status.HTTP_200_OK)

        except AlreadyLoggedException as exc:
            logger.error("Error in staff performance detail API: %s", exc.original)
            return _build_staff_error_response(
                message=(
                    "Internal server error occurred while generating staff "
                    "performance report"
                ),
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        except Exception as exc:
            logger.error(f"Error in staff performance detail API: {str(exc)}")
            app_error = persist_app_error(
                exc,
                additional_context={
                    "operation": "staff_performance_detail",
                    "staff_id": staff_id,
                    "start_date": start_date_str,
                    "end_date": end_date_str,
                },
            )
            return _build_staff_error_response(
                message=(
                    "Internal server error occurred while generating staff "
                    "performance report"
                ),
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                details={"error_id": str(app_error.id)},
            )
