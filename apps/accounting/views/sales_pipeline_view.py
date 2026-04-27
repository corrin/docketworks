"""API view for the Sales Pipeline Report."""

from logging import getLogger
from typing import Any, Type

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import Serializer
from rest_framework.views import APIView

from apps.accounting.serializers import (
    SalesPipelineQuerySerializer,
    SalesPipelineResponseSerializer,
    StandardErrorSerializer,
)
from apps.accounting.services import SalesPipelineService
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


class SalesPipelineAPIView(APIView):
    """Sales Pipeline Report — answers whether enough approved work is flowing
    into the shop, and where the bottleneck is. See
    ``docs/plans/2026-04-16-sales-pipeline-report.md``.
    """

    def get_serializer_class(self) -> Type[Serializer[Any]]:
        if self.request.method == "GET":
            return SalesPipelineResponseSerializer
        return SalesPipelineQuerySerializer

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="start_date",
                type=str,
                required=True,
                description="Inclusive ISO-8601 start of reporting period (NZ-local).",
            ),
            OpenApiParameter(
                name="end_date",
                type=str,
                required=False,
                description=(
                    "Inclusive ISO-8601 end of reporting period (NZ-local). "
                    "Defaults to today."
                ),
            ),
            OpenApiParameter(
                name="rolling_window_weeks",
                type=int,
                required=False,
                description="Window size for the trend rolling average. Default 4.",
            ),
            OpenApiParameter(
                name="trend_weeks",
                type=int,
                required=False,
                description="Number of weekly buckets in the trend. Default 13.",
            ),
        ],
        responses={
            200: SalesPipelineResponseSerializer,
            400: StandardErrorSerializer,
            500: StandardErrorSerializer,
        },
    )
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        try:
            query_serializer = SalesPipelineQuerySerializer(data=request.query_params)
            if not query_serializer.is_valid():
                return _build_standard_error_response(
                    message="Invalid query parameters",
                    status_code=status.HTTP_400_BAD_REQUEST,
                    details=query_serializer.errors,
                )

            params = query_serializer.validated_data
            report = SalesPipelineService.get_report(
                start_date=params["start_date"],
                end_date=params["end_date"],
                rolling_window_weeks=params["rolling_window_weeks"],
                trend_weeks=params["trend_weeks"],
            )

            response_serializer = SalesPipelineResponseSerializer(data=report)
            response_serializer.is_valid(raise_exception=True)
            return Response(response_serializer.data, status=status.HTTP_200_OK)

        except AlreadyLoggedException as exc:
            logger.error("Sales Pipeline API Error: %s", exc.original)
            details: dict[str, Any] | None = None
            if exc.app_error_id is not None:
                details = {"error_id": str(exc.app_error_id)}
            return _build_standard_error_response(
                message=f"Error obtaining sales pipeline data: {exc.original}",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                details=details,
            )
        except Exception as exc:
            logger.error(f"Sales Pipeline API Error: {str(exc)}")
            request_context = extract_request_context(request)
            app_error = persist_app_error(
                exc,
                user_id=request_context["user_id"],
                additional_context={
                    "operation": "sales_pipeline_api_endpoint",
                    "request_path": request_context["request_path"],
                    "request_method": request_context["request_method"],
                    "query_params": dict(request.query_params),
                },
            )
            return _build_standard_error_response(
                message=f"Error obtaining sales pipeline data: {str(exc)}",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                details={"error_id": str(app_error.id)},
            )
