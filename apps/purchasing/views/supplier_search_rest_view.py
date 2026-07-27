"""Supplier search REST view for purchase-order supplier lookup."""

import logging
from typing import Any

from drf_spectacular.utils import (
    OpenApiParameter,
    OpenApiTypes,
    extend_schema,
    extend_schema_view,
)
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.purchasing.serializers import SupplierSearchResponseSerializer
from apps.purchasing.services.supplier_search_service import (
    MAX_PAGE_SIZE,
    list_suppliers,
)
from apps.workflow.services.error_persistence import persist_app_error

logger = logging.getLogger(__name__)


def _build_server_error_response(*, message: str, exc: Exception) -> Response:
    app_error = persist_app_error(exc)

    logger.error("%s: %s", message, exc)

    payload: dict[str, Any] = {"error": message, "details": str(exc)}
    payload["error_id"] = str(app_error.id)
    return Response(payload, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@extend_schema_view(
    get=extend_schema(
        summary="Search purchase-order suppliers",
        parameters=[
            OpenApiParameter(
                name="q",
                location=OpenApiParameter.QUERY,
                required=False,
                description="Supplier search query.",
                type=OpenApiTypes.STR,
            ),
            OpenApiParameter(
                name="page",
                location=OpenApiParameter.QUERY,
                required=False,
                description="Page number (default 1)",
                type=OpenApiTypes.INT,
            ),
            OpenApiParameter(
                name="page_size",
                location=OpenApiParameter.QUERY,
                required=False,
                description="Results per page (default 50)",
                type=OpenApiTypes.INT,
            ),
        ],
        responses={200: SupplierSearchResponseSerializer},
        tags=["Purchasing"],
    )
)
class SupplierSearchRestView(APIView):
    """REST view for PO supplier lookup."""

    permission_classes = [IsAuthenticated]
    serializer_class = SupplierSearchResponseSerializer

    def get(self, request: Request) -> Response:
        try:
            query = (request.GET.get("q") or "").strip()

            try:
                page = max(1, int(request.GET.get("page", 1)))
            except ValueError:
                page = 1
            try:
                page_size = int(request.GET.get("page_size", 50))
            except ValueError:
                page_size = 50
            page_size = max(1, min(page_size, MAX_PAGE_SIZE))

            result = list_suppliers(
                query=query or None,
                page=page,
                page_size=page_size,
            )
            return Response(result)

        except ValueError as exc:
            return Response(
                {"error": "Invalid search query", "details": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception as exc:
            return _build_server_error_response(
                message="Error searching suppliers", exc=exc
            )
