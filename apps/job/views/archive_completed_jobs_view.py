import logging

from django.views.generic import TemplateView
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.job.permissions import IsOfficeStaff
from apps.job.serializers.job_serializer import (
    ArchiveJobsResponseSerializer,
    ArchiveJobsSerializer,
    CompleteJobSerializer,
)
from apps.job.services.job_service import archive_complete_jobs, get_paid_complete_jobs

logger = logging.getLogger(__name__)


class StandardResultsSetPagination(PageNumberPagination):
    """Standard pagination for job results."""

    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 100


class ArchiveCompleteJobsViews:
    """
    Class that centralizes views related to archiving completed paid jobs.
    Contains both TemplateView for template rendering and APIViews for receiving and sending data.
    """

    class ArchiveCompleteJobsTemplateView(TemplateView):
        """View for rendering the related page."""

        template_name = "jobs/archive_complete_jobs.html"

    class ArchiveCompleteJobsListAPIView(ListAPIView):
        """API Endpoint to provide Job data for archiving display"""

        serializer_class = CompleteJobSerializer
        permission_classes = [IsAuthenticated]
        pagination_class = StandardResultsSetPagination

        def get_queryset(self):
            """Return completed and paid jobs"""
            return get_paid_complete_jobs()

    class ArchiveCompleteJobsAPIView(APIView):
        """API Endpoint to set 'paid' flag as True in the received jobs"""

        permission_classes = [IsAuthenticated, IsOfficeStaff]

        @extend_schema(
            summary="Archive completed and paid jobs",
            request=ArchiveJobsSerializer,
            responses={
                200: ArchiveJobsResponseSerializer,
                207: ArchiveJobsResponseSerializer,
                400: ArchiveJobsResponseSerializer,
                500: ArchiveJobsResponseSerializer,
            },
        )
        def post(self, request, *args, **kwargs):
            try:
                # Validate request data
                request_serializer = ArchiveJobsSerializer(data=request.data)
                if not request_serializer.is_valid():
                    response_serializer = ArchiveJobsResponseSerializer(
                        data={
                            "success": False,
                            "error": "Invalid request data",
                            "errors": [str(request_serializer.errors)],
                        }
                    )
                    response_serializer.is_valid(raise_exception=True)
                    return Response(
                        response_serializer.data,
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                job_ids = request_serializer.validated_data["ids"]

                errors, archived_count = archive_complete_jobs(
                    job_ids, staff=request.user
                )

                if errors:
                    response_serializer = ArchiveJobsResponseSerializer(
                        data={
                            "success": archived_count > 0,
                            "message": f"Successfully archived {archived_count} jobs with {len(errors)} errors",
                            "errors": errors,
                        }
                    )
                    response_serializer.is_valid(raise_exception=True)
                    return Response(
                        response_serializer.data,
                        status=(
                            status.HTTP_207_MULTI_STATUS
                            if archived_count > 0
                            else status.HTTP_400_BAD_REQUEST
                        ),
                    )

                response_serializer = ArchiveJobsResponseSerializer(
                    data={
                        "success": True,
                        "message": f"Successfully archived {archived_count} jobs.",
                    }
                )
                response_serializer.is_valid(raise_exception=True)
                return Response(
                    response_serializer.data,
                    status=status.HTTP_200_OK,
                )

            except Exception as e:
                logger.exception(f"Unexpected error in archive jobs view: {str(e)}")
                response_serializer = ArchiveJobsResponseSerializer(
                    data={
                        "success": False,
                        "error": f"An unexpected error occurred: {str(e)}",
                    }
                )
                response_serializer.is_valid(raise_exception=True)
                return Response(
                    response_serializer.data,
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )
