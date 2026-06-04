import logging
from typing import Any, Dict

from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.workflow.exceptions import AlreadyLoggedException
from apps.workflow.search_telemetry_serializers import (
    SearchTelemetryClickRequestSerializer,
    SearchTelemetryClickResponseSerializer,
)
from apps.workflow.services.error_persistence import persist_app_error
from apps.workflow.services.search_telemetry import SearchTelemetryService

logger = logging.getLogger(__name__)


def _build_server_error_response(*, message: str, exc: Exception) -> Response:
    if isinstance(exc, AlreadyLoggedException):
        root_exc = exc.original
        error_id = exc.app_error_id
    else:
        root_exc = exc
        app_error = persist_app_error(exc)
        error_id = getattr(app_error, "id", None)

    logger.error("%s: %s", message, root_exc)

    payload: Dict[str, Any] = {"error": message, "details": str(root_exc)}
    if error_id:
        payload["error_id"] = str(error_id)
    return Response(payload, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@extend_schema_view(
    post=extend_schema(
        summary="Log search result selection",
        description="Records a selected result from client, Kanban, or stock search.",
        request=SearchTelemetryClickRequestSerializer,
        responses={200: SearchTelemetryClickResponseSerializer},
        tags=["Search telemetry"],
    )
)
class SearchTelemetryClickAPIView(APIView):
    """Generic REST endpoint for search click telemetry."""

    permission_classes = [IsAuthenticated]
    serializer_class = SearchTelemetryClickRequestSerializer

    def post(self, request: Request) -> Response:
        try:
            serializer = SearchTelemetryClickRequestSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            data = serializer.validated_data
            SearchTelemetryService.log_click(
                request=request,
                domain=data["domain"],
                source=data.get("source") or f"{data['domain']}_search",
                query=data["query"],
                selected_result_id=data["selected_result_id"],
                selected_label=data.get("selected_label") or "",
                selected_rank=data.get("selected_rank"),
                result_count=data.get("result_count") or 0,
                filters=data.get("filters") or {},
                metadata=data.get("metadata") or {},
            )
            response_serializer = SearchTelemetryClickResponseSerializer(
                data={"success": True}
            )
            response_serializer.is_valid(raise_exception=True)
            return Response(response_serializer.data)
        except Exception as exc:
            return _build_server_error_response(
                message="Error logging search telemetry", exc=exc
            )
