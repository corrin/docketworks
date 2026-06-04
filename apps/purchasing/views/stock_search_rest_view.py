"""
Stock search REST view.

Mirrors ClientSearchRestView in shape: paginated list with an optional `q`
parameter that runs Postgres FTS over the stock table. The 3-character
minimum-query guard matches client search.
"""

import logging
from typing import Any, Dict

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

from apps.purchasing.serializers import StockSearchResponseSerializer
from apps.purchasing.services.stock_search_service import MAX_PAGE_SIZE, list_stock
from apps.workflow.exceptions import AlreadyLoggedException
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
    get=extend_schema(
        summary="Search stock",
        parameters=[
            OpenApiParameter(
                name="q",
                location=OpenApiParameter.QUERY,
                required=False,
                description=(
                    "Search query (Postgres FTS, websearch syntax). "
                    "Queries shorter than 3 characters return all stock."
                ),
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
            OpenApiParameter(
                name="sort_by",
                location=OpenApiParameter.QUERY,
                required=False,
                description="Field to sort by (default 'description')",
                type=OpenApiTypes.STR,
            ),
            OpenApiParameter(
                name="sort_dir",
                location=OpenApiParameter.QUERY,
                required=False,
                description="Sort direction: 'asc' or 'desc' (default 'asc')",
                type=OpenApiTypes.STR,
            ),
        ],
        responses={200: StockSearchResponseSerializer},
        tags=["Stock"],
    )
)
class StockSearchRestView(APIView):
    """REST view for paginated stock search."""

    permission_classes = [IsAuthenticated]
    serializer_class = StockSearchResponseSerializer

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

            sort_by = request.GET.get("sort_by", "description")
            sort_dir = request.GET.get("sort_dir", "asc")

            result = list_stock(
                query=query if len(query) >= 3 else None,
                page=page,
                page_size=page_size,
                sort_by=sort_by,
                sort_dir=sort_dir,
            )
            if len(query) >= 3:
                SearchTelemetryService.log_search(
                    request=request,
                    domain="stock",
                    source="stock_search",
                    query=query,
                    result_count=result["count"],
                    returned_result_ids=[
                        item["id"] for item in result["results"] if item.get("id")
                    ],
                    metadata={
                        "page": result["page"],
                        "page_size": result["page_size"],
                        "sort_by": sort_by,
                        "sort_dir": sort_dir,
                        "results": [
                            {
                                "rank": index + 1,
                                "stock_id": item.get("id"),
                                "item_code": item.get("item_code"),
                                "description": item.get("description"),
                            }
                            for index, item in enumerate(result["results"][:100])
                        ],
                    },
                )

            # `result["results"]` is already serialized via StockItemSerializer
            # in list_stock. Re-running it through `StockSearchResponseSerializer
            # (data=...).is_valid()` would re-trigger the ModelSerializer's
            # unique-validator on item_code and reject every row (because they
            # exist in the DB — they are the DB rows). Trust the service output.
            return Response(result)

        except ValueError as exc:
            return Response(
                {"error": "Invalid search query", "details": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception as exc:
            return _build_server_error_response(
                message="Error searching stock", exc=exc
            )
