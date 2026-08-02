"""The JobFile model: files attached to a job on disk."""

import uuid
from pathlib import Path
from typing import ClassVar

from django.db import models

from apps.job.helpers import get_job_folder_path


class JobFile(models.Model):  # noqa: DJ008 -- v1 defines no __str__; adding one would change behaviour
    """A file stored against a job (uploads, generated dockets, etc.)."""

    # CHECKLIST - when adding a new field or property to JobFile, check these locations:
    #   1. JOBFILE_API_FIELDS or JOBFILE_INTERNAL_FIELDS below (if it's a model field)
    #   2. JobFileOut in apps/job/schemas.py and job_file_data() in
    #      apps/job/services/job_service.py (the one serialisation, ADR 0039)
    #   3. sync_job_folder()/save_uploaded_job_file() in
    #      apps/job/services/file_service.py (create JobFile records)
    #   4. generate_delivery_docket() in apps/job/services/delivery_docket_service.py
    #      (creates JobFile)
    #   5. create_image_document()/get_pdf_file_paths() in
    #      apps/job/services/workshop_pdf_service.py (use file_path, filename)
    #
    # Database fields exposed via API serializers
    JOBFILE_API_FIELDS: ClassVar[list[str]] = [
        "id",
        "filename",
        "mime_type",
        "uploaded_at",
        "status",
        "print_on_jobsheet",
    ]

    # Computed properties exposed via API serializers
    JOBFILE_API_PROPERTIES: ClassVar[list[str]] = [
        "size",
        "download_url",
        "thumbnail_url",
    ]

    # Internal fields not exposed in API
    JOBFILE_INTERNAL_FIELDS: ClassVar[list[str]] = [
        "job",
        "file_path",
    ]

    # All JobFile model fields (derived)
    JOBFILE_ALL_FIELDS: ClassVar[list[str]] = JOBFILE_API_FIELDS + JOBFILE_INTERNAL_FIELDS

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.ForeignKey("Job", related_name="files", on_delete=models.CASCADE)
    filename = models.CharField(max_length=255)
    file_path = models.CharField(max_length=500)
    mime_type = models.CharField(max_length=100, blank=True, null=True)  # noqa: DJ001 -- v1 schema parity
    uploaded_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(
        max_length=20,
        choices=[("active", "Active"), ("deleted", "Deleted")],
        default="active",
    )
    print_on_jobsheet = models.BooleanField(default=True)

    class Meta:
        ordering: ClassVar[list[str]] = ["-uploaded_at"]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=~models.Q(mime_type=""), name="job_jobfile_mime_type_not_blank"
            ),
        ]

    @property
    def full_path(self) -> str:
        """Full system path to the job folder holding this file (v1 shape)."""
        return get_job_folder_path(self.job.job_number)

    @property
    def url(self) -> str:
        """URL to serve the file (if using Django to serve media)."""
        return f"/jobs/files/{self.file_path}"  # We'll need to add this URL pattern

    @property
    def thumbnail_path(self) -> str | None:
        """Return path to thumbnail if one exists."""
        if self.status == "deleted":
            return None

        # Function-local import: file_service is a service layer module and
        # this model is imported by it transitively (v1 had the same shape).
        from apps.job.services.file_service import (  # noqa: PLC0415 -- model->service cycle (v1 parity)
            get_thumbnail_folder,
        )

        thumb_path = Path(get_thumbnail_folder(self.job.job_number)) / f"{self.filename}.thumb.jpg"
        return str(thumb_path) if thumb_path.exists() else None

    @property
    def size(self) -> int | None:
        """Return size of file in bytes."""
        if self.status == "deleted":
            return None

        file_path = Path(self.full_path) / self.filename
        return file_path.stat().st_size if file_path.exists() else None
