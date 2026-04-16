from logging import getLogger

from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema
from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.job.models import CostLine, Job
from apps.job.serializers.kanban_serializer import WorkshopJobSerializer
from apps.job.services.workshop_service import WorkshopTimesheetService
from apps.timesheet.serializers.modern_timesheet_serializers import (
    WorkshopTimesheetDeleteRequestSerializer,
    WorkshopTimesheetEntryRequestSerializer,
    WorkshopTimesheetEntrySerializer,
    WorkshopTimesheetEntryUpdateSerializer,
    WorkshopTimesheetListResponseSerializer,
)
from apps.workflow.services.error_persistence import persist_app_error

logger = getLogger(__name__)


class WorkshopKanbanView(ListAPIView):
    serializer_class = WorkshopJobSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Retrieve jobs for the workshop kanban view."""
        staff = self.request.user
        logger.info(f"Fetching in-progress jobs for staff ID: {staff.id}")
        jobs = Job.objects.filter(people__id=staff.id, status__in=["in_progress"])
        logger.info(f"Retrieved {jobs.count()} jobs for staff ID: {staff.id}")

        return [
            {
                "id": job.id,
                "name": job.name,
                "description": job.description,
                "job_number": job.job_number,
                "client_name": job.client.name,
                "contact_person": job.contact.name if job.contact else None,
                "people": [
                    {
                        "id": staff.id,
                        "display_name": f"{staff.preferred_name or staff.first_name} {staff.last_name}",
                        "icon_url": staff.icon.url if staff.icon else None,
                    }
                    for staff in job.people.all()
                ],
            }
            for job in jobs
        ]


class WorkshopTimesheetView(APIView):
    """
    API for workshop staff to manage their own timesheet entries (CostLines).

    GET    -> Returns entries for the requested (or current) day
    POST   -> Creates a new time CostLine for the authenticated staff
    PATCH  -> Updates an existing CostLine owned by the staff member
    """

    permission_classes = [IsAuthenticated]
    serializer_class = WorkshopTimesheetEntrySerializer

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="date",
                type=OpenApiTypes.DATE,
                location=OpenApiParameter.QUERY,
                description="Optional date (YYYY-MM-DD). Defaults to today.",
                required=False,
            )
        ],
        responses={
            status.HTTP_200_OK: WorkshopTimesheetListResponseSerializer,
            status.HTTP_400_BAD_REQUEST: OpenApiTypes.OBJECT,
            status.HTTP_500_INTERNAL_SERVER_ERROR: OpenApiTypes.OBJECT,
        },
    )
    def get(self, request):
        """Return all timesheet entries for the staff member on a given date."""
        staff = request.user

        service = WorkshopTimesheetService(staff=staff)
        try:
            entry_date = WorkshopTimesheetService.resolve_entry_date(
                request.query_params.get("date")
            )
            entries, summary = service.list_entries(entry_date=entry_date)
            return Response(
                {
                    "date": entry_date,
                    "entries": WorkshopTimesheetEntrySerializer(
                        entries, many=True
                    ).data,
                    "summary": summary,
                }
            )
        except ValueError as exc:
            logger.info("Invalid date for workshop timesheet get: %s", exc)
            return Response(
                {"error": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception as exc:
            persist_app_error(exc, user_id=str(staff.id))
            logger.exception("Failed to fetch workshop timesheet entries")
            return Response(
                {"error": "Failed to fetch workshop timesheet entries."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @extend_schema(
        request=WorkshopTimesheetEntryRequestSerializer,
        responses={
            status.HTTP_201_CREATED: WorkshopTimesheetEntrySerializer,
            status.HTTP_400_BAD_REQUEST: OpenApiTypes.OBJECT,
            status.HTTP_404_NOT_FOUND: OpenApiTypes.OBJECT,
            status.HTTP_500_INTERNAL_SERVER_ERROR: OpenApiTypes.OBJECT,
        },
    )
    def post(self, request):
        """Create a new timesheet entry for the authenticated staff."""
        staff = request.user
        serializer = WorkshopTimesheetEntryRequestSerializer(data=request.data)
        if not serializer.is_valid():
            logger.info("Invalid workshop timesheet payload: %s", serializer.errors)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        job_id = str(data["job_id"])
        service = WorkshopTimesheetService(staff=staff)

        try:
            cost_line = service.create_entry(data=data)
            response_data = WorkshopTimesheetEntrySerializer(cost_line).data
            return Response(response_data, status=status.HTTP_201_CREATED)
        except Job.DoesNotExist:
            return Response(
                {"error": "Job not found."}, status=status.HTTP_404_NOT_FOUND
            )
        except Exception as exc:
            persist_app_error(
                exc,
                user_id=str(staff.id),
                job_id=job_id,
            )
            logger.exception("Failed to create workshop timesheet entry")
            return Response(
                {"error": "Failed to create timesheet entry."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @extend_schema(
        request=WorkshopTimesheetEntryUpdateSerializer,
        responses={
            status.HTTP_200_OK: WorkshopTimesheetEntrySerializer,
            status.HTTP_400_BAD_REQUEST: OpenApiTypes.OBJECT,
            status.HTTP_403_FORBIDDEN: OpenApiTypes.OBJECT,
            status.HTTP_404_NOT_FOUND: OpenApiTypes.OBJECT,
            status.HTTP_500_INTERNAL_SERVER_ERROR: OpenApiTypes.OBJECT,
        },
    )
    def patch(self, request):
        """Update an existing timesheet entry belonging to the staff member."""
        staff = request.user
        serializer = WorkshopTimesheetEntryUpdateSerializer(
            data=request.data, partial=True
        )
        if not serializer.is_valid():
            logger.info(
                "Invalid workshop timesheet patch payload: %s", serializer.errors
            )
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        service = WorkshopTimesheetService(staff=staff)

        try:
            cost_line = service.update_entry(data=data)
            response_data = WorkshopTimesheetEntrySerializer(cost_line).data
            return Response(response_data)
        except Job.DoesNotExist:
            return Response(
                {"error": "Job not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        except CostLine.DoesNotExist:
            return Response(
                {"error": "Timesheet entry not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        except PermissionError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            job_id = None
            if "cost_line" in locals():
                job_id = getattr(cost_line.cost_set, "job_id", None)
                if job_id:
                    job_id = str(job_id)
            persist_app_error(
                exc,
                user_id=str(staff.id),
                job_id=job_id,
            )
            logger.exception("Failed to update workshop timesheet entry")
            return Response(
                {"error": "Failed to update timesheet entry."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="entry_id",
                type=str,
                required=True,
                location=OpenApiParameter.QUERY,
                description="UUID of the timesheet entry to delete.",
            ),
        ],
        responses={
            status.HTTP_204_NO_CONTENT: None,
            status.HTTP_400_BAD_REQUEST: OpenApiTypes.OBJECT,
            status.HTTP_403_FORBIDDEN: OpenApiTypes.OBJECT,
            status.HTTP_404_NOT_FOUND: OpenApiTypes.OBJECT,
            status.HTTP_500_INTERNAL_SERVER_ERROR: OpenApiTypes.OBJECT,
        },
    )
    def delete(self, request):
        """Delete a timesheet entry belonging to the staff member."""
        staff = request.user
        serializer = WorkshopTimesheetDeleteRequestSerializer(data=request.query_params)
        if not serializer.is_valid():
            logger.info(
                "Invalid workshop timesheet delete payload: %s", serializer.errors
            )
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        service = WorkshopTimesheetService(staff=staff)

        try:
            service.delete_entry(entry_id=str(data["entry_id"]))
            return Response(status=status.HTTP_204_NO_CONTENT)
        except CostLine.DoesNotExist:
            return Response(
                {"error": "Timesheet entry not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        except PermissionError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        except Exception as exc:
            persist_app_error(
                exc,
                user_id=str(staff.id),
            )
            logger.exception("Failed to delete workshop timesheet entry")
            return Response(
                {"error": "Failed to delete timesheet entry."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
