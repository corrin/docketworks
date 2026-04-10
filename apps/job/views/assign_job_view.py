import logging

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.job.permissions import IsStaffUser
from apps.job.serializers import AssignJobResponseSerializer, AssignJobSerializer
from apps.job.services.job_service import JobStaffService

logger = logging.getLogger(__name__)


class JobAssignmentCreateView(APIView):
    """API Endpoint to assign staff to a job (POST /api/job/<job_id>/assignment)"""

    permission_classes = [IsAuthenticated, IsStaffUser]

    @extend_schema(
        request=AssignJobSerializer,
        responses={status.HTTP_200_OK: AssignJobResponseSerializer},
    )
    def post(self, request, job_id):
        try:
            request_serializer = AssignJobSerializer(data=request.data)
            if not request_serializer.is_valid():
                response_serializer = AssignJobResponseSerializer(
                    data={"success": False, "error": "Invalid request data"}
                )
                response_serializer.is_valid(raise_exception=True)
                return Response(
                    response_serializer.data,
                    status=status.HTTP_400_BAD_REQUEST,
                )

            staff_id = request_serializer.validated_data["staff_id"]

            success, error = JobStaffService.assign_staff_to_job(job_id, staff_id)

            if not success:
                logger.warning(
                    "Staff assignment failed: job=%s staff=%s error=%s",
                    job_id,
                    staff_id,
                    error,
                )

            if success:
                response_serializer = AssignJobResponseSerializer(
                    data={
                        "success": True,
                        "message": "Job assigned to staff successfully.",
                    }
                )
                response_serializer.is_valid(raise_exception=True)
                return Response(
                    response_serializer.data,
                    status=status.HTTP_200_OK,
                )

            response_serializer = AssignJobResponseSerializer(
                data={"success": False, "error": error}
            )
            response_serializer.is_valid(raise_exception=True)
            return Response(
                response_serializer.data, status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            response_serializer = AssignJobResponseSerializer(
                data={"success": False, "error": str(e)}
            )
            response_serializer.is_valid(raise_exception=True)
            return Response(
                response_serializer.data,
                status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class JobAssignmentDeleteView(APIView):
    """API Endpoint to remove staff from a job (DELETE /api/job/<job_id>/assignment/<staff_id>)"""

    permission_classes = [IsAuthenticated, IsStaffUser]

    @extend_schema(
        responses={status.HTTP_200_OK: AssignJobResponseSerializer},
    )
    def delete(self, request, job_id, staff_id):
        try:
            success, error = JobStaffService.remove_staff_from_job(job_id, staff_id)

            if success:
                response_serializer = AssignJobResponseSerializer(
                    data={
                        "success": True,
                        "message": "Staff removed from job successfully.",
                    }
                )
                response_serializer.is_valid(raise_exception=True)
                return Response(
                    response_serializer.data,
                    status=status.HTTP_200_OK,
                )

            response_serializer = AssignJobResponseSerializer(
                data={"success": False, "error": error}
            )
            response_serializer.is_valid(raise_exception=True)
            return Response(
                response_serializer.data, status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            logger.error(f"Error removing staff from job: {e}")
            response_serializer = AssignJobResponseSerializer(
                data={"success": False, "error": str(e)}
            )
            response_serializer.is_valid(raise_exception=True)
            return Response(
                response_serializer.data,
                status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
