"""
Job Files Collection View - Collection operations on /jobs/{job_id}/files/

Handles:
- POST: Upload files to a job
- GET: List all files for a job

All identifiers (job_id) are in URL path, NOT request body.
"""

import logging
import os

from django.conf import settings
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.job.models import Job, JobFile
from apps.job.serializers.job_file_serializer import (
    JobFileErrorResponseSerializer,
    JobFileSerializer,
    JobFileUploadPartialResponseSerializer,
    JobFileUploadSerializer,
    JobFileUploadSuccessResponseSerializer,
)
from apps.job.tasks import create_job_file_thumbnail_task
from apps.workflow.exceptions import AlreadyLoggedException
from apps.workflow.services.error_persistence import (
    persist_and_raise,
    persist_app_error,
)

logger = logging.getLogger(__name__)


class JobFilesCollectionView(APIView):
    """
    Collection operations on job files.

    URL: /rest/jobs/{job_id}/files/
    Methods: POST (upload), GET (list)
    """

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def save_file(self, job, file_obj, print_on_jobsheet, request):
        """Save file to disk and create JobFile record."""
        job_folder = os.path.join(
            settings.DROPBOX_WORKFLOW_FOLDER, f"Job-{job.job_number}"
        )
        os.makedirs(job_folder, exist_ok=True)
        safe_filename = os.path.basename(file_obj.name)
        file_path = os.path.join(job_folder, safe_filename)

        # Fail early if empty
        if file_obj.size == 0:
            raise ValueError(f"Uploaded file {file_obj.name} is empty (0 bytes)")

        try:
            # Write file
            with open(file_path, "wb") as destination:
                for chunk in file_obj.chunks():
                    destination.write(chunk)

            # Create database record
            relative_path = os.path.relpath(file_path, settings.DROPBOX_WORKFLOW_FOLDER)
            job_file, created = JobFile.objects.update_or_create(
                job=job,
                filename=safe_filename,
                defaults={
                    "file_path": relative_path,
                    "mime_type": file_obj.content_type,
                    "print_on_jobsheet": print_on_jobsheet,
                    "status": "active",
                },
            )

            logger.info(
                "%s file: %s for job %s",
                "Created" if created else "Updated",
                file_obj.name,
                job.job_number,
            )

            serialized_file = JobFileSerializer(
                job_file, context={"request": request}
            ).data

            # Generate thumbnails asynchronously so uploads are not blocked by
            # image processing.
            if file_obj.content_type and file_obj.content_type.startswith("image/"):
                try:
                    create_job_file_thumbnail_task.delay(str(job_file.id))
                except AlreadyLoggedException:
                    logger.exception(
                        "Thumbnail generation failed after upload for file %s",
                        job_file.id,
                    )
                except Exception as thumb_exc:
                    logger.exception(
                        "Could not enqueue thumbnail generation for file %s",
                        job_file.id,
                    )
                    persist_app_error(
                        thumb_exc,
                        job_id=str(job.id),
                        user_id=(
                            str(request.user.id)
                            if getattr(request.user, "is_authenticated", False)
                            else None
                        ),
                        additional_context={"file_id": str(job_file.id)},
                    )

            return serialized_file

        except Exception as e:
            logger.error("Error saving file %s: %s", file_obj.name, str(e))
            persist_and_raise(
                e,
                job_id=str(job.id),
                user_id=(
                    str(request.user.id)
                    if getattr(request.user, "is_authenticated", False)
                    else None
                ),
                additional_context={"filename": file_obj.name},
            )

    @extend_schema(
        operation_id="uploadJobFiles",
        request=JobFileUploadSerializer,
        responses={
            201: JobFileUploadSuccessResponseSerializer,
            207: JobFileUploadPartialResponseSerializer,
            400: JobFileErrorResponseSerializer,
        },
        description="Upload files to a job. Job ID (UUID) is in URL path.",
        tags=["Job Files"],
    )
    def post(self, request, job_id):
        """Upload files to a job."""
        if not getattr(request.user, "is_office_staff", False):
            return Response(
                {
                    "status": "error",
                    "message": "Only office staff can upload job files.",
                },
                status=status.HTTP_403_FORBIDDEN,
            )
        job = get_object_or_404(Job, id=job_id)

        files_payload = request.FILES.getlist("files")
        request_serializer = JobFileUploadSerializer(
            data={
                "files": files_payload,
                "print_on_jobsheet": request.data.get("print_on_jobsheet", True),
            }
        )
        if not request_serializer.is_valid():
            return Response(
                {
                    "status": "error",
                    "message": "Invalid input data",
                    "errors": request_serializer.errors,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        files = request_serializer.validated_data["files"]
        print_on_jobsheet = request_serializer.validated_data.get(
            "print_on_jobsheet", True
        )
        uploaded_files, errors = [], []

        # Process each file
        for file_obj in files:
            try:
                result = self.save_file(job, file_obj, print_on_jobsheet, request)
                uploaded_files.append(result)
            except Exception as e:
                errors.append(f"Failed to upload {file_obj.name}: {str(e)}")

        # Return response
        if errors:
            response_status = (
                status.HTTP_207_MULTI_STATUS
                if uploaded_files
                else status.HTTP_400_BAD_REQUEST
            )
            response_data = {
                "status": "partial_success" if uploaded_files else "error",
                "uploaded": uploaded_files,
                "errors": errors,
            }
            return Response(response_data, status=response_status)

        return Response(
            {
                "status": "success",
                "uploaded": uploaded_files,
                "message": "Files uploaded successfully",
            },
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(
        operation_id="listJobFiles",
        responses={
            200: JobFileSerializer(many=True),
            404: JobFileErrorResponseSerializer,
        },
        description="List all active files for a job.",
        tags=["Job Files"],
    )
    def get(self, request, job_id):
        """List files for a job."""
        job = get_object_or_404(Job, id=job_id)

        # Get active files
        files = JobFile.objects.filter(job=job, status="active").select_related("job")
        serializer = JobFileSerializer(files, many=True, context={"request": request})
        return Response(serializer.data, status=status.HTTP_200_OK)
