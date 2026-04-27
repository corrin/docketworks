import logging
from typing import Any

from django.db import models
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Staff
from apps.operations.models import AllocationBlock, JobProjection, SchedulerRun
from apps.operations.serializers.workshop_schedule_serializer import (
    DaySerializer,
    ScheduledJobSerializer,
    UnscheduledJobSerializer,
    WorkshopScheduleQuerySerializer,
    WorkshopScheduleResponseSerializer,
)
from apps.operations.services.capacity import booked_hours_by_staff_date
from apps.workflow.models.company_defaults import CompanyDefaults
from apps.workflow.services.error_persistence import (
    extract_request_context,
    persist_app_error,
)

logger = logging.getLogger(__name__)


def _build_schedule_response(day_horizon: int) -> dict[str, Any]:
    latest_run = SchedulerRun.objects.filter(succeeded=True).order_by("-ran_at").first()
    if latest_run is None:
        return {"days": [], "jobs": [], "unscheduled_jobs": []}

    projections = (
        JobProjection.objects.filter(scheduler_run=latest_run)
        .select_related("job", "job__client")
        .prefetch_related("job__people")
    )

    scheduled_jobs = []
    unscheduled_jobs = []

    for projection in projections:
        job = projection.job
        client_name = job.client.name if job.client else ""

        if projection.is_unscheduled:
            unscheduled_jobs.append(
                {
                    "id": job.id,
                    "job_number": job.job_number,
                    "name": job.name,
                    "client_name": client_name,
                    "delivery_date": job.delivery_date,
                    "remaining_hours": projection.remaining_hours,
                    "reason": projection.unscheduled_reason or "",
                }
            )
        else:
            anticipated_staff_qs = Staff.objects.filter(
                allocation_blocks__job=job,
                allocation_blocks__scheduler_run=latest_run,
            ).distinct()
            anticipated_staff = [
                {"id": s.id, "name": s.name} for s in anticipated_staff_qs
            ]

            assigned_staff = [{"id": s.id, "name": s.name} for s in job.people.all()]

            scheduled_jobs.append(
                {
                    "id": job.id,
                    "job_number": job.job_number,
                    "name": job.name,
                    "client_name": client_name,
                    "remaining_hours": projection.remaining_hours,
                    "delivery_date": job.delivery_date,
                    "anticipated_start_date": projection.anticipated_start_date,
                    "anticipated_end_date": projection.anticipated_end_date,
                    "is_late": projection.is_late,
                    "min_people": job.min_people,
                    "max_people": job.max_people,
                    "assigned_staff": assigned_staff,
                    "anticipated_staff": anticipated_staff,
                }
            )

    today = timezone.localdate()

    distinct_dates = (
        AllocationBlock.objects.filter(scheduler_run=latest_run)
        .values_list("allocation_date", flat=True)
        .distinct()
        .order_by("allocation_date")[:day_horizon]
    )

    all_workshop_staff = list(
        Staff.objects.filter(is_workshop_staff=True).filter(
            models.Q(date_left__isnull=True) | models.Q(date_left__gt=today)
        )
    )

    allocated_by_date = dict(
        AllocationBlock.objects.filter(
            scheduler_run=latest_run,
            allocation_date__in=list(distinct_dates),
        )
        .values("allocation_date")
        .annotate(total=models.Sum("allocated_hours"))
        .values_list("allocation_date", "total")
    )

    distinct_dates_list = list(distinct_dates)
    if distinct_dates_list:
        booked_hours = booked_hours_by_staff_date(
            distinct_dates_list[0], distinct_dates_list[-1]
        )
    else:
        booked_hours = {}

    efficiency_factor = float(CompanyDefaults.get_solo().workshop_efficiency_factor)

    days = []
    for day_date in distinct_dates_list:
        total_capacity = 0.0
        for s in all_workshop_staff:
            nominal = s.get_scheduled_hours(day_date)
            already_booked = booked_hours.get((str(s.pk), day_date), 0.0)
            total_capacity += max(0.0, nominal - already_booked) * efficiency_factor
        allocated = float(allocated_by_date.get(day_date, 0.0) or 0.0)
        utilisation_pct = (
            (allocated / total_capacity * 100) if total_capacity > 0 else 0.0
        )
        days.append(
            {
                "date": day_date,
                "total_capacity_hours": total_capacity,
                "allocated_hours": allocated,
                "utilisation_pct": utilisation_pct,
            }
        )

    return {
        "days": DaySerializer(days, many=True).data,
        "jobs": ScheduledJobSerializer(scheduled_jobs, many=True).data,
        "unscheduled_jobs": UnscheduledJobSerializer(unscheduled_jobs, many=True).data,
    }


class WorkshopScheduleView(APIView):
    """GET /api/operations/workshop-schedule/"""

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="day_horizon",
                type=int,
                required=False,
                description="Number of days to include in the response (default 14, max 365)",
            )
        ],
        responses={200: WorkshopScheduleResponseSerializer},
    )
    def get(self, request: Request) -> Response:
        query_serializer = WorkshopScheduleQuerySerializer(data=request.query_params)
        if not query_serializer.is_valid():
            return Response(query_serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        day_horizon = query_serializer.validated_data["day_horizon"]

        try:
            response_data = _build_schedule_response(day_horizon)
            return Response(response_data)
        except Exception as exc:
            request_context = extract_request_context(request)
            persist_app_error(
                exc,
                user_id=request_context["user_id"],
                additional_context={
                    "operation": "workshop_schedule_get",
                    "request_path": request_context["request_path"],
                    "day_horizon": day_horizon,
                },
            )
            return Response(
                {"error": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class WorkshopScheduleRecalculateView(APIView):
    """POST /api/operations/workshop-schedule/recalculate/"""

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="day_horizon",
                type=int,
                required=False,
                description="Number of days to include in the response (default 14, max 365)",
            )
        ],
        request=None,
        responses={200: WorkshopScheduleResponseSerializer},
    )
    def post(self, request: Request) -> Response:
        query_serializer = WorkshopScheduleQuerySerializer(data=request.query_params)
        if not query_serializer.is_valid():
            return Response(query_serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        day_horizon = query_serializer.validated_data["day_horizon"]

        try:
            from apps.operations.services.scheduler_service import (
                run_workshop_schedule,
            )

            run_workshop_schedule()
            response_data = _build_schedule_response(day_horizon)
            return Response(response_data)
        except Exception as exc:
            request_context = extract_request_context(request)
            persist_app_error(
                exc,
                user_id=request_context["user_id"],
                additional_context={
                    "operation": "workshop_schedule_recalculate",
                    "request_path": request_context["request_path"],
                    "day_horizon": day_horizon,
                },
            )
            return Response(
                {"error": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
