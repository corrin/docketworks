from logging import getLogger
from typing import Any, Type

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import Serializer
from rest_framework.views import APIView

from apps.accounting.serializers import StandardErrorSerializer
from apps.accounting.serializers.rdti_spend_serializers import (
    RDTISpendQuerySerializer,
    RDTISpendResponseSerializer,
)
from apps.accounting.services.rdti_spend_service import RDTISpendService
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


class RDTISpendAPIView(APIView):
    """API endpoint for the RDTI spend report."""

    def get_serializer_class(self) -> Type[Serializer[Any]]:
        if self.request.method == "GET":
            return RDTISpendResponseSerializer
        return RDTISpendQuerySerializer

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
        responses={200: RDTISpendResponseSerializer, 400: StandardErrorSerializer},
    )
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        try:
            query_serializer = RDTISpendQuerySerializer(data=request.query_params)
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

            data = RDTISpendService.get_rdti_spend_data(
                start_date=query_serializer.validated_data["start_date"],
                end_date=query_serializer.validated_data["end_date"],
            )

            response_serializer = RDTISpendResponseSerializer(data=data)
            response_serializer.is_valid(raise_exception=True)

            return Response(response_serializer.data, status=status.HTTP_200_OK)

        except AlreadyLoggedException as exc:
            logger.error("RDTI Spend API Error: %s", exc.original)
            return _build_standard_error_response(
                message=f"Error obtaining RDTI spend data: {exc.original}",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        except Exception as exc:
            logger.error(f"RDTI Spend API Error: {str(exc)}")

            request_context = extract_request_context(request)
            app_error = persist_app_error(
                exc,
                user_id=request_context["user_id"],
                additional_context={
                    "operation": "rdti_spend_api_endpoint",
                    "request_path": request_context["request_path"],
                    "request_method": request_context["request_method"],
                    "query_params": dict(request.query_params),
                },
            )

            return _build_standard_error_response(
                message=f"Error obtaining RDTI spend data: {str(exc)}",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                details={"error_id": str(app_error.id)},
            )
