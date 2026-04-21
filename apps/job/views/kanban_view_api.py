"""
Kanban views - API endpoints for kanban board functionality.
All business logic delegated to KanbanService.
"""

import logging
import traceback
from uuid import UUID

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.job.models import Job
from apps.job.permissions import IsStaffUser
from apps.job.serializers import (
    AdvancedSearchResponseSerializer,
    FetchAllJobsResponseSerializer,
    FetchJobsByColumnResponseSerializer,
    FetchJobsResponseSerializer,
    FetchStatusValuesResponseSerializer,
    JobReorderSerializer,
    JobStatusUpdateSerializer,
    KanbanErrorResponseSerializer,
    KanbanSuccessResponseSerializer,
)
from apps.job.services.kanban_service import KanbanService

logger = logging.getLogger(__name__)


class FetchAllJobsAPIView(APIView):
    """
    Fetch all jobs for Kanban board - API endpoint.
    """

    permission_classes = [IsAuthenticated, IsStaffUser]
    serializer_class = FetchAllJobsResponseSerializer

    def get(self, request: Request) -> Response:
        try:
            # Get active jobs
            active_jobs = KanbanService.get_all_active_jobs()

            # Get archived jobs
            archived_jobs = KanbanService.get_archived_jobs(50)

            # Serialize jobs
            active_job_data = [
                KanbanService.serialize_job_for_api(job, request) for job in active_jobs
            ]

            archived_job_data = [
                KanbanService.serialize_job_for_api(job, request)
                for job in archived_jobs
            ]

            response_data = {
                "success": True,
                "active_jobs": active_job_data,
                "archived_jobs": archived_job_data,
                "total_archived": Job.objects.filter(status="archived").count(),
            }

            success_serializer = FetchAllJobsResponseSerializer(data=response_data)
            success_serializer.is_valid(raise_exception=True)
            return Response(success_serializer.data)
        except Exception as e:
            tb = traceback.format_exc()
            logger.error(f"Error fetching all jobs: {e}\n{tb}")

            error_response = {
                "success": False,
                "error": str(e),
                "active_jobs": [],
                "archived_jobs": [],
                "total_archived": 0,
            }
            error_serializer = FetchAllJobsResponseSerializer(data=error_response)
            error_serializer.is_valid(raise_exception=True)
            return Response(
                error_serializer.data, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class UpdateJobStatusAPIView(APIView):
    """Update job status - API endpoint."""

    permission_classes = [IsAuthenticated, IsStaffUser]
    serializer_class = KanbanSuccessResponseSerializer

    def get_serializer_class(self):
        """Return the serializer class for documentation"""
        if self.request.method == "POST":
            return JobStatusUpdateSerializer
        return KanbanSuccessResponseSerializer

    def get_serializer(self, *args, **kwargs):
        """Return the serializer instance for the request for OpenAPI compatibility"""
        serializer_class = self.get_serializer_class()
        return serializer_class(*args, **kwargs)

    @extend_schema(
        request=JobStatusUpdateSerializer,
        responses={
            200: KanbanSuccessResponseSerializer,
            400: KanbanErrorResponseSerializer,
            404: KanbanErrorResponseSerializer,
            500: KanbanErrorResponseSerializer,
        },
        description="Update the status of a job on the Kanban board.",
    )
    def post(self, request: Request, job_id: UUID) -> Response:
        try:
            # Validate input data
            serializer = JobStatusUpdateSerializer(data=request.data)
            if not serializer.is_valid():
                error_response = {
                    "success": False,
                    "error": f"Invalid input data: {serializer.errors}",
                }
                error_serializer = KanbanErrorResponseSerializer(data=error_response)
                error_serializer.is_valid(raise_exception=True)
                return Response(
                    error_serializer.data, status=status.HTTP_400_BAD_REQUEST
                )

            new_status = serializer.validated_data["status"]

            KanbanService.update_job_status(job_id, new_status, staff=request.user)

            # Return success response
            success_response = {
                "success": True,
                "message": "Job status updated successfully",
            }
            success_serializer = KanbanSuccessResponseSerializer(data=success_response)
            success_serializer.is_valid(raise_exception=True)
            return Response(success_serializer.data)

        except Job.DoesNotExist:
            error_response = {"success": False, "error": "Job not found"}
            error_serializer = KanbanErrorResponseSerializer(data=error_response)
            error_serializer.is_valid(raise_exception=True)
            return Response(error_serializer.data, status=status.HTTP_404_NOT_FOUND)

        except Exception as e:
            logger.error(f"Error updating job status: {e}")
            error_response = {"success": False, "error": str(e)}
            error_serializer = KanbanErrorResponseSerializer(data=error_response)
            error_serializer.is_valid(raise_exception=True)
            return Response(
                error_serializer.data, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class ReorderJobAPIView(APIView):
    """Reorder job within or between columns - API endpoint."""

    permission_classes = [IsAuthenticated]
    serializer_class = KanbanSuccessResponseSerializer

    def get_serializer_class(self):
        """Return the serializer class for documentation"""
        if self.request.method == "POST":
            return JobReorderSerializer
        return KanbanSuccessResponseSerializer

    def get_serializer(self, *args, **kwargs):
        """Return the serializer instance for the request for OpenAPI compatibility"""
        serializer_class = self.get_serializer_class()
        return serializer_class(*args, **kwargs)

    @extend_schema(
        request=JobReorderSerializer,
        responses={
            200: KanbanSuccessResponseSerializer,
            400: KanbanErrorResponseSerializer,
            404: KanbanErrorResponseSerializer,
            500: KanbanErrorResponseSerializer,
        },
        description="Reorder a job within or between kanban columns.",
    )
    def post(self, request: Request, job_id: UUID) -> Response:
        try:
            # Validate input data
            serializer = JobReorderSerializer(data=request.data)
            if not serializer.is_valid():
                error_response = {
                    "success": False,
                    "error": f"Invalid input data: {serializer.errors}",
                }
                error_serializer = KanbanErrorResponseSerializer(data=error_response)
                error_serializer.is_valid(raise_exception=True)
                return Response(
                    error_serializer.data, status=status.HTTP_400_BAD_REQUEST
                )

            validated_data = serializer.validated_data
            before_id = validated_data.get("before_id")
            after_id = validated_data.get("after_id")
            new_status = validated_data.get("status")

            KanbanService.reorder_job(
                job_id, before_id, after_id, new_status, staff=request.user
            )

            # Return success response
            success_response = {
                "success": True,
                "message": "Job reordered successfully",
            }
            success_serializer = KanbanSuccessResponseSerializer(data=success_response)
            success_serializer.is_valid(raise_exception=True)
            return Response(success_serializer.data)

        except Job.DoesNotExist:
            error_response = {"success": False, "error": "Job not found"}
            error_serializer = KanbanErrorResponseSerializer(data=error_response)
            error_serializer.is_valid(raise_exception=True)
            return Response(error_serializer.data, status=status.HTTP_404_NOT_FOUND)

        except Exception as e:
            logger.error(f"Error reordering job: {e}")
            error_response = {"success": False, "error": str(e)}
            error_serializer = KanbanErrorResponseSerializer(data=error_response)
            error_serializer.is_valid(raise_exception=True)
            return Response(
                error_serializer.data, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class FetchJobsAPIView(APIView):
    """Fetch jobs by status with optional search - API endpoint."""

    permission_classes = [IsAuthenticated]
    serializer_class = FetchJobsResponseSerializer

    def get(self, request: Request, status: str) -> Response:
        try:
            search_term = request.GET.get("search", "").strip()
            search_terms = search_term.split() if search_term else []

            jobs = KanbanService.get_jobs_by_status(status, search_terms)
            total_jobs = Job.objects.filter(status=status).count()

            job_data = [
                KanbanService.serialize_job_for_api(job, request) for job in jobs
            ]

            response_data = {
                "success": True,
                "jobs": job_data,
                "total": total_jobs,
                "filtered_count": len(job_data),
            }
            success_serializer = FetchJobsResponseSerializer(data=response_data)
            success_serializer.is_valid(raise_exception=True)
            return Response(success_serializer.data)

        except Exception as e:
            logger.error(f"Error fetching jobs by status {status}: {e}")
            error_response = {
                "success": False,
                "error": str(e),
                "jobs": [],
                "total": 0,
                "filtered_count": 0,
            }
            error_serializer = FetchJobsResponseSerializer(data=error_response)
            error_serializer.is_valid(raise_exception=True)
            return Response(
                error_serializer.data, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class FetchStatusValuesAPIView(APIView):
    """Return available status values for Kanban - API endpoint."""

    permission_classes = [IsAuthenticated]
    serializer_class = FetchStatusValuesResponseSerializer

    def get(self, request: Request) -> Response:
        try:
            status_data = KanbanService.get_status_choices()
            response_data = {"success": True, **status_data}
            success_serializer = FetchStatusValuesResponseSerializer(data=response_data)
            success_serializer.is_valid(raise_exception=True)
            return Response(success_serializer.data)

        except Exception as e:
            logger.error(f"Error fetching status values: {e}")
            error_response = {
                "success": False,
                "error": str(e),
                "statuses": {},
                "tooltips": {},
            }
            error_serializer = FetchStatusValuesResponseSerializer(data=error_response)
            error_serializer.is_valid(raise_exception=True)
            return Response(
                error_serializer.data, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class AdvancedSearchAPIView(APIView):
    """Endpoint for advanced job search - API endpoint."""

    permission_classes = [IsAuthenticated]
    serializer_class = AdvancedSearchResponseSerializer

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="q",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Universal search - searches across job number, name, description, and client name with OR logic",
            ),
            OpenApiParameter(
                name="job_number",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter by job number",
            ),
            OpenApiParameter(
                name="name",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter by job name",
            ),
            OpenApiParameter(
                name="description",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter by job description",
            ),
            OpenApiParameter(
                name="client_name",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter by client name",
            ),
            OpenApiParameter(
                name="contact_person",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter by contact person",
            ),
            OpenApiParameter(
                name="created_by",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter by creator",
            ),
            OpenApiParameter(
                name="created_after",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter jobs created after this date (YYYY-MM-DD)",
            ),
            OpenApiParameter(
                name="created_before",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter jobs created before this date (YYYY-MM-DD)",
            ),
            OpenApiParameter(
                name="status",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter by job status (can be multiple)",
            ),
            OpenApiParameter(
                name="paid",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter by paid status",
            ),
            OpenApiParameter(
                name="rejected_flag",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter by rejected status",
            ),
            OpenApiParameter(
                name="xero_invoice_params",
                type=str,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Filter by Xero invoice parameters",
            ),
        ],
        responses={200: AdvancedSearchResponseSerializer},
    )
    def get(self, request: Request) -> Response:
        try:
            # Extract filters from GET parameters
            filters = {
                "universal_search": request.GET.get("q", ""),
                "job_number": request.GET.get("job_number", ""),
                "name": request.GET.get("name", ""),
                "description": request.GET.get("description", ""),
                "client_name": request.GET.get("client_name", ""),
                "contact_person": request.GET.get("contact_person", ""),
                "created_by": request.GET.get("created_by", ""),
                "created_after": request.GET.get("created_after", ""),
                "created_before": request.GET.get("created_before", ""),
                "paid": request.GET.get("paid", ""),
                "rejected_flag": request.GET.get("rejected_flag", ""),
                "xero_invoice_params": request.GET.get("xero_invoice_params", ""),
            }

            # Handle multiple status values
            raw = request.GET.get("status", "")
            filters["status"] = raw.split(",") if raw else []

            jobs = KanbanService.perform_advanced_search(filters)

            job_data = [
                KanbanService.serialize_job_for_api(job, request) for job in jobs
            ]

            response_data = {
                "success": True,
                "jobs": job_data,
                "total": len(job_data),
            }
            success_serializer = AdvancedSearchResponseSerializer(data=response_data)
            success_serializer.is_valid(raise_exception=True)
            return Response(success_serializer.data)

        except Exception as e:
            logger.error(f"Error in advanced search: {e}")
            error_response = {
                "success": False,
                "error": str(e),
                "jobs": [],
                "total": 0,
            }
            error_serializer = AdvancedSearchResponseSerializer(data=error_response)
            error_serializer.is_valid(raise_exception=True)
            return Response(
                error_serializer.data, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class FetchJobsByColumnAPIView(APIView):
    """Fetch jobs by kanban column using new categorization system."""

    permission_classes = [IsAuthenticated]
    serializer_class = FetchJobsByColumnResponseSerializer

    def get(self, request: Request, column_id: str) -> Response:
        try:
            max_jobs = int(request.GET.get("max_jobs", 100))
            search_term = request.GET.get("search", "")

            # Use the new categorized kanban service
            result = KanbanService.get_jobs_by_kanban_column(
                column_id, max_jobs, search_term
            )

            # Serialize the response
            response_serializer = FetchJobsByColumnResponseSerializer(data=result)
            response_serializer.is_valid(raise_exception=True)
            logger.debug(
                f"Response data for column {column_id}: jobs order = {[job['job_number'] for job in response_serializer.data.get('jobs', [])]}"
            )
            return Response(response_serializer.data)

        except ValueError as e:
            logger.error(f"Invalid parameter in fetch_jobs_by_column: {e}")
            error_response = {
                "success": False,
                "error": "Invalid parameters",
                "jobs": [],
                "total": 0,
                "filtered_count": 0,
            }
            error_serializer = FetchJobsByColumnResponseSerializer(data=error_response)
            error_serializer.is_valid(raise_exception=True)
            return Response(error_serializer.data, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"Error fetching jobs for column {column_id}: {e}")
            error_response = {
                "success": False,
                "error": str(e),
                "jobs": [],
                "total": 0,
                "filtered_count": 0,
            }
            error_serializer = FetchJobsByColumnResponseSerializer(data=error_response)
            error_serializer.is_valid(raise_exception=True)
            return Response(
                error_serializer.data, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
