from datetime import date
from logging import getLogger
from typing import Any, Type

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import Serializer
from rest_framework.views import APIView

from apps.accounting.serializers import StandardErrorSerializer
from apps.accounting.serializers.wip_serializers import (
    WIPQuerySerializer,
    WIPResponseSerializer,
)
from apps.accounting.services.wip_service import WIPService
from apps.workflow.exceptions import AlreadyLoggedException
from apps.workflow.services.error_persistence import (
    extract_request_context,
    persist_app_error,
)

logger = getLogger(__name__)


def _build_standard_error_response(
    *, message: str, status_code: int, details: dict[str, Any] | None = None
) -> Response:
    payload: dict[str, Any] = {"error": message}
    if details is not None:
        payload["details"] = details

    serializer = StandardErrorSerializer(data=payload)
    serializer.is_valid(raise_exception=True)
    return Response(serializer.data, status=status_code)


class WIPReportAPIView(APIView):
    """API endpoint for Work In Progress report."""

    def get_serializer_class(self) -> Type[Serializer[Any]]:
        """Return the serializer class for documentation."""
        if self.request.method == "GET":
            return WIPResponseSerializer
        return WIPQuerySerializer

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="date",
                type=str,
                required=False,
                description="Report date in YYYY-MM-DD format. Defaults to today.",
            ),
            OpenApiParameter(
                name="method",
                type=str,
                required=False,
                enum=["revenue", "cost"],
                description="Valuation method. Defaults to 'revenue'.",
            ),
        ],
        responses={200: WIPResponseSerializer, 400: StandardErrorSerializer},
    )
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        Get WIP data as at a given date.

        Query Parameters:
            date (str): Report date in YYYY-MM-DD format. Defaults to today.
            method (str): Valuation method — 'revenue' (default) or 'cost'.

        Returns:
            JSON response with WIP data, archived jobs, and summary.
        """
        try:
            query_serializer = WIPQuerySerializer(data=request.query_params)
            if not query_serializer.is_valid():
                error_serializer = StandardErrorSerializer(
                    data={
                        "error": "Invalid query parameters",
                        "details": query_serializer.errors,
                    }
                )
                error_serializer.is_valid(raise_exception=True)
                return Response(
                    error_serializer.data,
                    status=status.HTTP_400_BAD_REQUEST,
                )

            report_date = query_serializer.validated_data.get("date", date.today())
            method = query_serializer.validated_data.get("method", "revenue")

            wip_data = WIPService.get_wip_data(report_date, method)

            response_serializer = WIPResponseSerializer(data=wip_data)
            response_serializer.is_valid(raise_exception=True)

            return Response(response_serializer.data, status=status.HTTP_200_OK)

        except AlreadyLoggedException as exc:
            logger.error("WIP Report API Error: %s", exc.original)
            return _build_standard_error_response(
                message=f"Error generating WIP report: {exc.original}",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        except Exception as exc:
            logger.error("WIP Report API Error: %s", exc)

            request_context = extract_request_context(request)
            app_error = persist_app_error(
                exc,
                user_id=request_context["user_id"],
                additional_context={
                    "operation": "wip_report_api_endpoint",
                    "request_path": request_context["request_path"],
                    "request_method": request_context["request_method"],
                    "query_params": dict(request.query_params),
                },
            )

            return _build_standard_error_response(
                message=f"Error generating WIP report: {exc}",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                details={"error_id": str(app_error.id)},
            )
