from uuid import UUID

from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema
from rest_framework import filters, status
from rest_framework.decorators import action
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import ReadOnlyModelViewSet

from apps.job.permissions import IsOfficeStaff
from apps.workflow.api.pagination import FiftyPerPagePagination
from apps.workflow.models import AppError
from apps.workflow.serializers import AppErrorListResponseSerializer, AppErrorSerializer
from apps.workflow.services.error_persistence import list_app_errors
from apps.workflow.utils import parse_pagination_params

APP_ERROR_REST_LIST_PARAMETERS = [
    OpenApiParameter("limit", OpenApiTypes.INT, OpenApiParameter.QUERY, required=False),
    OpenApiParameter(
        "offset", OpenApiTypes.INT, OpenApiParameter.QUERY, required=False
    ),
    OpenApiParameter("app", OpenApiTypes.STR, OpenApiParameter.QUERY, required=False),
    OpenApiParameter(
        "severity", OpenApiTypes.INT, OpenApiParameter.QUERY, required=False
    ),
    OpenApiParameter(
        "resolved", OpenApiTypes.BOOL, OpenApiParameter.QUERY, required=False
    ),
    OpenApiParameter(
        "job_id", OpenApiTypes.UUID, OpenApiParameter.QUERY, required=False
    ),
    OpenApiParameter(
        "user_id", OpenApiTypes.UUID, OpenApiParameter.QUERY, required=False
    ),
]


class AppErrorListAPIView(ListAPIView):
    """
    API view for listing application errors.

    Returns a paginated list of all AppError records ordered by timestamp
    (most recent first). Includes filtering capabilities for debugging and
    monitoring application issues.

    Endpoint: /api/app-errors/
    """

    queryset = AppError.objects.all().order_by("-timestamp")
    serializer_class = AppErrorSerializer
    pagination_class = FiftyPerPagePagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ["app", "severity", "resolved", "job_id", "user_id"]
    search_fields = ["message", "function", "file"]
    permission_classes = [IsAuthenticated, IsOfficeStaff]


class AppErrorDetailAPIView(RetrieveAPIView):
    """
    API view for retrieving a single application error.

    Returns detailed information about a specific AppError record
    including error message, context, location, and resolution status.
    Used for investigating specific application failures.

    Endpoint: /api/app-errors/<id>/
    """

    queryset = AppError.objects.all()
    serializer_class = AppErrorSerializer
    permission_classes = [IsAuthenticated, IsOfficeStaff]


class AppErrorRestListView(APIView):
    """
    REST-style view that exposes AppError telemetry for admin monitoring.

    Supports pagination via ``limit``/``offset`` query params and optional filters:
    - ``app`` (icontains match)
    - ``severity`` (exact integer)
    - ``resolved`` (boolean)
    - ``job_id`` / ``user_id`` (UUID strings)
    """

    serializer_class = AppErrorListResponseSerializer
    permission_classes = [IsAuthenticated, IsOfficeStaff]

    @extend_schema(
        parameters=APP_ERROR_REST_LIST_PARAMETERS,
        responses={200: AppErrorListResponseSerializer},
    )
    def get(self, request):
        try:
            limit, offset = parse_pagination_params(request)
        except ValueError:
            return Response(
                {"error": "Invalid pagination parameters"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        resolved_param = request.query_params.get("resolved")
        resolved: bool | None = None
        if resolved_param is not None:
            value = resolved_param.strip().lower()
            if value in {"true", "1", "yes"}:
                resolved = True
            elif value in {"false", "0", "no"}:
                resolved = False
            else:
                return Response(
                    {"error": "Invalid resolved parameter"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        severity_param = request.query_params.get("severity")
        severity: int | None = None
        if severity_param is not None:
            try:
                severity = int(severity_param)
            except ValueError:
                return Response(
                    {"error": "Invalid severity parameter"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        def _cast_uuid(value: str | None, field: str) -> str | None:
            if not value:
                return None
            try:
                return str(UUID(str(value)))
            except ValueError:
                raise ValueError(f"Invalid {field} parameter")

        try:
            job_id = _cast_uuid(request.query_params.get("job_id"), "job_id")
            user_id = _cast_uuid(request.query_params.get("user_id"), "user_id")
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        payload = list_app_errors(
            limit=limit,
            offset=offset,
            app=request.query_params.get("app"),
            severity=severity,
            resolved=resolved,
            job_id=job_id,
            user_id=user_id,
        )

        serializer = self.serializer_class(payload)
        return Response(serializer.data, status=status.HTTP_200_OK)


class AppErrorViewSet(ReadOnlyModelViewSet):
    """
    ViewSet for AppError with filtering capabilities and resolution actions.

    Provides list, retrieve, and resolution management for application errors.
    Includes comprehensive filtering and search capabilities for error analysis.

    Endpoints:
    - GET /api/app-errors/
    - GET /api/app-errors/<id>/
    - POST /api/app-errors/<id>/mark_resolved/
    - POST /api/app-errors/<id>/mark_unresolved/
    """

    queryset = AppError.objects.all().order_by("-timestamp")
    serializer_class = AppErrorSerializer
    pagination_class = FiftyPerPagePagination
    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    filterset_fields = {
        "app": ["exact", "icontains"],
        "file": ["exact", "icontains"],
        "function": ["exact", "icontains"],
        "severity": ["exact", "gte", "lte"],
        "job_id": ["exact"],
        "user_id": ["exact"],
        "resolved": ["exact"],
        "timestamp": ["gte", "lte"],
    }
    search_fields = ["message", "function", "file", "app"]
    ordering_fields = ["timestamp", "severity", "app", "resolved"]
    ordering = ["-timestamp"]
    permission_classes = [IsAuthenticated, IsOfficeStaff]

    @action(detail=True, methods=["post"])
    def mark_resolved(self, request, pk=None):
        """Mark an error as resolved."""
        error = self.get_object()

        # Get the current user (staff member)
        if hasattr(request.user, "staff_profile"):
            staff_member = request.user.staff_profile
        else:
            staff_member = None

        error.mark_resolved(staff_member)

        return Response(
            {
                "status": "resolved",
                "resolved_by": staff_member.id if staff_member else None,
                "resolved_timestamp": error.resolved_timestamp,
            }
        )

    @action(detail=True, methods=["post"])
    def mark_unresolved(self, request, pk=None):
        """Mark an error as unresolved."""
        error = self.get_object()

        # Get the current user (staff member)
        if hasattr(request.user, "staff_profile"):
            staff_member = request.user.staff_profile
        else:
            staff_member = None

        error.mark_unresolved(staff_member)

        return Response(
            {
                "status": "unresolved",
                "resolved": False,
                "resolved_by": None,
                "resolved_timestamp": None,
            }
        )
