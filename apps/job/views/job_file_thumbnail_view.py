"""
Job File Thumbnail View - Thumbnail serving for /jobs/{job_id}/files/{file_id}/thumbnail/

Handles:
- GET: Serve JPEG thumbnail for a job file (images only)

All identifiers (job_id, file_id) are in URL path, NOT request body.
"""

import logging
import os

from django.http import FileResponse
from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.job.models import Job, JobFile
from apps.job.serializers.job_file_serializer import (
    JobFileThumbnailErrorResponseSerializer,
)
from apps.workflow.services.error_persistence import persist_app_error

logger = logging.getLogger(__name__)


class JobFileThumbnailView(APIView):
    """
    Thumbnail serving for job files.

    URL: /rest/jobs/{job_id}/files/{file_id}/thumbnail/
    Methods: GET
    """

    permission_classes = [IsAuthenticated]
    serializer_class = JobFileThumbnailErrorResponseSerializer

    @extend_schema(
        operation_id="getJobFileThumbnail",
        responses={
            200: OpenApiResponse(
                response=OpenApiTypes.BINARY,
                description="JPEG thumbnail image",
            ),
            404: JobFileThumbnailErrorResponseSerializer,
        },
        description="Get JPEG thumbnail for a job file (images only).",
        tags=["Job Files"],
    )
    def get(self, request, job_id, file_id):
        """Serve thumbnail for a job file."""
        job = get_object_or_404(Job, id=job_id)

        # Get file
        job_file = get_object_or_404(JobFile, id=file_id, job=job, status="active")
        thumb_path = job_file.thumbnail_path

        if not thumb_path or not os.path.exists(thumb_path):
            return Response(
                {"status": "error", "message": "Thumbnail not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            return FileResponse(open(thumb_path, "rb"), content_type="image/jpeg")
        except Exception as e:
            logger.exception("Error serving thumbnail %s", file_id)
            app_error = persist_app_error(
                e,
                job_id=str(job.id),
                user_id=(
                    str(request.user.id)
                    if getattr(request.user, "is_authenticated", False)
                    else None
                ),
                additional_context={"file_id": str(file_id)},
            )
            payload = {
                "status": "error",
                "message": "Could not serve thumbnail",
                "error_id": str(app_error.id),
            }
            return Response(
                payload,
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
