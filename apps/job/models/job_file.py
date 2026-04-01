import os
import uuid

from django.db import models

from apps.job.helpers import get_job_folder_path
from apps.job.services.file_service import get_thumbnail_folder


class JobFile(models.Model):
    # CHECKLIST - when adding a new field or property to JobFile, check these locations:
    #   1. JOBFILE_API_FIELDS or JOBFILE_INTERNAL_FIELDS below (if it's a model field)
    #   2. JobFileSerializer in apps/job/serializers/job_file_serializer.py (uses JOBFILE_API_FIELDS)
    #   3. UploadedFileSerializer in apps/job/serializers/job_file_serializer.py (upload response)
    #   4. sync_job_files() in apps/job/services/file_service.py (creates JobFile records)
    #   5. create_delivery_docket() in apps/job/services/delivery_docket_service.py (creates JobFile)
    #   6. _add_images_to_pdf() in apps/job/services/workshop_pdf_service.py (uses file_path, filename)
    #
    # Database fields exposed via API serializers
    JOBFILE_API_FIELDS = [
        "id",
        "filename",
        "mime_type",
        "uploaded_at",
        "status",
        "print_on_jobsheet",
    ]

    # Computed properties exposed via API serializers
    JOBFILE_API_PROPERTIES = [
        "size",
        "download_url",
        "thumbnail_url",
    ]

    # Internal fields not exposed in API
    JOBFILE_INTERNAL_FIELDS = [
        "job",
        "file_path",
    ]

    # All JobFile model fields (derived)
    JOBFILE_ALL_FIELDS = JOBFILE_API_FIELDS + JOBFILE_INTERNAL_FIELDS

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.ForeignKey("Job", related_name="files", on_delete=models.CASCADE)
    filename = models.CharField(max_length=255)
    file_path = models.CharField(max_length=500)
    mime_type = models.CharField(max_length=100, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(
        max_length=20,
        choices=[("active", "Active"), ("deleted", "Deleted")],
        default="active",
    )
    print_on_jobsheet = models.BooleanField(default=True)

    @property
    def full_path(self):
        """Full system path to the file."""
        return get_job_folder_path(self.job.job_number)

    @property
    def url(self):
        """URL to serve the file (if using Django to serve media)."""
        return f"/jobs/files/{self.file_path}"  # We'll need to add this URL pattern

    @property
    def thumbnail_path(self):
        """Return path to thumbnail if one exists."""
        if self.status == "deleted":
            return None

        thumb_path = os.path.join(
            get_thumbnail_folder(self.job.job_number), f"{self.filename}.thumb.jpg"
        )
        return thumb_path if os.path.exists(thumb_path) else None

    @property
    def size(self):
        """Return size of file in bytes."""
        if self.status == "deleted":
            return None

        file_path = os.path.join(self.full_path, self.filename)
        return os.path.getsize(file_path) if os.path.exists(file_path) else None

    class Meta:
        ordering = ["-uploaded_at"]
