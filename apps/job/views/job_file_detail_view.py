"""
Job File Detail View - Resource operations on /jobs/{job_id}/files/{file_id}/

Handles:
- GET: Download/view a specific file
- PUT: Update file metadata
- DELETE: Delete a file

All identifiers (job_id, file_id) are in URL path, NOT request body.
"""

import logging
import mimetypes
import os

from django.conf import settings
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import BaseRenderer, JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.job.models import Job, JobFile
from apps.job.serializers.job_file_serializer import (
    JobFileErrorResponseSerializer,
    JobFileSerializer,
    JobFileUpdateSuccessResponseSerializer,
)
from apps.workflow.services.error_persistence import persist_app_error

logger = logging.getLogger(__name__)


class BinaryFileRenderer(BaseRenderer):
    """Renderer for binary file content."""

    media_type = "*/*"
    format = "file"

    def render(self, data, accepted_media_type=None, renderer_context=None):
        return data


class JobFileDetailView(APIView):
    """
    Resource operations on individual job files.

    URL: /rest/jobs/{job_id}/files/{file_id}/
    Methods: GET (download), PUT (update), DELETE (delete)
    """

    permission_classes = [IsAuthenticated]
    renderer_classes = [JSONRenderer, BinaryFileRenderer]
    serializer_class = JobFileSerializer

    @extend_schema(
        operation_id="getJobFile",
        responses={
            200: OpenApiResponse(
                response=OpenApiTypes.BINARY,
                description="Binary file content",
            ),
            404: JobFileErrorResponseSerializer,
        },
        description="Download/view a specific job file.",
        tags=["Job Files"],
    )
    def get(self, request, job_id, file_id):
        """Serve file content for download/viewing."""
        job = get_object_or_404(Job, id=job_id)

        # Get file
        job_file = get_object_or_404(JobFile, id=file_id, job=job, status="active")
        full_path = os.path.join(settings.DROPBOX_WORKFLOW_FOLDER, job_file.file_path)

        if not os.path.exists(full_path):
            return Response(
                {"status": "error", "message": "File not found on disk"},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            response = FileResponse(open(full_path, "rb"))
            content_type, _ = mimetypes.guess_type(full_path)
            if content_type:
                response["Content-Type"] = content_type
            response["Content-Disposition"] = f'inline; filename="{job_file.filename}"'
            return response
        except Exception as e:
            logger.exception("Error serving file %s", file_id)
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
                "message": str(e),
                "error_id": str(app_error.id),
            }
            return Response(
                payload,
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @extend_schema(
        operation_id="updateJobFile",
        responses={
            200: JobFileUpdateSuccessResponseSerializer,
            400: JobFileErrorResponseSerializer,
            404: JobFileErrorResponseSerializer,
        },
        description="Update job file metadata.",
        tags=["Job Files"],
    )
    def put(self, request, job_id, file_id):
        """Update file metadata."""
        if not getattr(request.user, "is_office_staff", False):
            return Response(
                {"status": "error", "message": "Only office staff can update files."},
                status=status.HTTP_403_FORBIDDEN,
            )
        job = get_object_or_404(Job, id=job_id)

        # Get file
        job_file = get_object_or_404(JobFile, id=file_id, job=job, status="active")

        try:
            # Update print_on_jobsheet if provided
            if "print_on_jobsheet" in request.data:
                print_value = str(request.data.get("print_on_jobsheet")).lower()
                job_file.print_on_jobsheet = print_value in ["true", "1"]

            # Update filename if provided
            if "filename" in request.data:
                new_filename = request.data.get("filename")
                if not new_filename:
                    return Response(
                        {"status": "error", "message": "Filename cannot be empty"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                old_path = os.path.join(
                    settings.DROPBOX_WORKFLOW_FOLDER, job_file.file_path
                )
                new_path = os.path.join(os.path.dirname(old_path), new_filename)

                if not os.path.exists(old_path):
                    return Response(
                        {
                            "status": "error",
                            "message": "Original file does not exist; cannot rename.",
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                # Prevent overwriting an existing file with a different path
                if os.path.exists(new_path) and (
                    os.path.normcase(new_path) != os.path.normcase(old_path)
                ):
                    return Response(
                        {
                            "status": "error",
                            "message": "A file with the requested new filename already exists.",
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                os.rename(old_path, new_path)

                # Update database only after successful rename
                job_file.filename = new_filename
                job_file.file_path = os.path.relpath(
                    new_path, settings.DROPBOX_WORKFLOW_FOLDER
                )

            job_file.save()

            logger.info("Updated file %s (job %s)", file_id, job_id)

            return Response(
                {
                    "status": "success",
                    "message": "File updated successfully",
                    "print_on_jobsheet": job_file.print_on_jobsheet,
                    "filename": job_file.filename,
                },
                status=status.HTTP_200_OK,
            )

        except Exception as e:
            logger.exception("Error updating file %s", file_id)
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
                "message": str(e),
                "error_id": str(app_error.id),
            }
            return Response(
                payload,
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @extend_schema(
        operation_id="deleteJobFile",
        responses={
            204: None,
            404: JobFileErrorResponseSerializer,
            500: JobFileErrorResponseSerializer,
        },
        description="Delete a job file.",
        tags=["Job Files"],
    )
    def delete(self, request, job_id, file_id):
        """Delete a job file."""
        if not getattr(request.user, "is_office_staff", False):
            return Response(
                {"status": "error", "message": "Only office staff can delete files."},
                status=status.HTTP_403_FORBIDDEN,
            )
        job = get_object_or_404(Job, id=job_id)

        try:
            # Get file
            job_file = get_object_or_404(JobFile, id=file_id, job=job)
            full_path = os.path.join(
                settings.DROPBOX_WORKFLOW_FOLDER, job_file.file_path
            )

            # Delete physical file
            if os.path.exists(full_path):
                os.remove(full_path)

            # Delete thumbnail if exists
            if job_file.thumbnail_path and os.path.exists(job_file.thumbnail_path):
                os.remove(job_file.thumbnail_path)

            # Delete database record
            job_file.delete()

            logger.info("Deleted file %s (job %s)", file_id, job_id)

            return Response(status=status.HTTP_204_NO_CONTENT)

        except Exception as e:
            logger.exception("Error deleting file %s", file_id)
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
                "message": str(e),
                "error_id": str(app_error.id),
            }
            return Response(
                payload,
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
