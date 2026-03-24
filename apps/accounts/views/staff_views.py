import logging
from datetime import datetime
from uuid import UUID

from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import (
    OpenApiParameter,
    extend_schema,
    extend_schema_view,
    inline_serializer,
)
from rest_framework import generics, serializers
from rest_framework.decorators import api_view
from rest_framework.permissions import IsAuthenticated

from apps.accounts.models import Staff
from apps.accounts.serializers import KanbanStaffSerializer
from apps.accounts.utils import get_excluded_staff

logger = logging.getLogger(__name__)


@extend_schema_view(
    get=extend_schema(
        parameters=[
            OpenApiParameter(
                name="date",
                type=OpenApiTypes.DATE,
                location=OpenApiParameter.QUERY,
                description="Filter staff active on specific date (YYYY-MM-DD format).",
                required=False,
            ),
            OpenApiParameter(
                name="include_inactive",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description='Include inactive staff. Pass "true" to include.',
                required=False,
                enum=["true", "false"],
                default="false",
            ),
            OpenApiParameter(
                name="actual_users",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                description='Exclude system/test accounts. Pass "true" to exclude.',
                required=False,
                enum=["true", "false"],
                default="false",
            ),
        ]
    )
)
class StaffListAPIView(generics.ListAPIView):
    """API endpoint for retrieving list of staff members for Kanban board.

    Supports filtering to return only actual users (excluding system/test accounts)
    based on the 'actual_users' query parameter.
    """

    queryset = Staff.objects.all()
    serializer_class = KanbanStaffSerializer
    permission_classes = [IsAuthenticated]

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        serializer = KanbanStaffSerializer(queryset, many=True)
        return JsonResponse(serializer.data, safe=False)

    def get_queryset(self):
        # Parse parameters upfront
        date_param = self.request.GET.get("date")
        target_date = (
            datetime.strptime(date_param, "%Y-%m-%d").date() if date_param else None
        )
        actual_users = self.request.GET.get("actual_users", "false").lower() == "true"
        include_inactive = (
            self.request.GET.get("include_inactive", "false").lower() == "true"
        )

        logger.info(
            f"Fetching staff list with filters:"
            f" actual_users={actual_users}"
            f" date={target_date or 'not specified'}"
            f" include_inactive={include_inactive}"
        )

        # Build queryset using manager methods
        if target_date:
            queryset = Staff.objects.active_on_date(target_date)
        elif include_inactive:
            queryset = Staff.objects.all()
        else:
            queryset = Staff.objects.currently_active()

        if actual_users:
            excluded_ids = [
                UUID(id_str) for id_str in get_excluded_staff(target_date=target_date)
            ]
            queryset = queryset.exclude(id__in=excluded_ids)

        return queryset

    def get_serializer_context(self):
        return {"request": self.request}


@extend_schema(
    operation_id="getStaffRates",
    summary="Retrieve wage rates for a specific staff member",
    tags=["Staff Management"],
    responses={
        200: inline_serializer(
            "StaffRatesResponse",
            fields={
                "base_wage_rate": serializers.FloatField(),
                "wage_rate": serializers.FloatField(),
            },
        ),
        403: inline_serializer(
            "StaffRatesErrorResponse",
            fields={"error": serializers.CharField()},
        ),
    },
)
@api_view(["GET"])
def get_staff_rates(request, staff_id):
    """Retrieve wage rates for a specific staff member.

    Returns JSON response with staff member's wage rate information.
    Restricted to authenticated staff managers only.
    """
    if not request.user.is_authenticated or not request.user.is_staff_manager():
        return JsonResponse({"error": "Unauthorized"}, status=403)
    staff = get_object_or_404(Staff, id=staff_id)
    rates = {
        "base_wage_rate": float(staff.base_wage_rate),
        "wage_rate": float(staff.wage_rate),
    }
    return JsonResponse(rates)
