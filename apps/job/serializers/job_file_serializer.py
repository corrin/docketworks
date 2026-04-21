from django.urls import reverse
from rest_framework import serializers

from apps.job.models import JobFile


class JobFileSerializer(serializers.ModelSerializer):
    # force DRF to treat `id` as an input field, and require it
    id = serializers.UUIDField(required=True, allow_null=False)

    download_url = serializers.SerializerMethodField()
    thumbnail_url = serializers.SerializerMethodField()
    size = serializers.SerializerMethodField()

    class Meta:
        model = JobFile
        fields = JobFile.JOBFILE_API_FIELDS + JobFile.JOBFILE_API_PROPERTIES

    def get_size(self, obj: JobFile) -> int | None:
        """Get file size in bytes"""
        return obj.size

    def get_download_url(self, obj: JobFile) -> str:
        # Relative path so the browser resolves it against the SPA's origin and
        # sends the host-only auth cookie. An absolute URL built from Django's
        # Host header can point to a different origin (the upstream host behind
        # the Vite dev proxy / nginx), which silently drops the cookie.
        return reverse(
            "jobs:job_file_detail", kwargs={"job_id": obj.job.id, "file_id": obj.id}
        )

    def get_thumbnail_url(self, obj: JobFile) -> str | None:
        if not obj.thumbnail_path:
            return None
        return reverse(
            "jobs:job_file_thumbnail", kwargs={"job_id": obj.job.id, "file_id": obj.id}
        )


class UploadedFileSerializer(serializers.Serializer):
    """Serializer for file upload response."""

    id = serializers.CharField()
    filename = serializers.CharField()
    file_path = serializers.CharField()
    print_on_jobsheet = serializers.BooleanField()


class JobFileUploadSerializer(serializers.Serializer):
    """Serializer for job file upload requests."""

    files = serializers.ListField(
        child=serializers.FileField(),
        allow_empty=False,
        help_text="Files to upload",
    )
    print_on_jobsheet = serializers.BooleanField(
        required=False,
        default=True,
        help_text="Flag indicating whether the file should print on the jobsheet.",
    )


class JobFileUploadSuccessResponseSerializer(serializers.Serializer):
    """Serializer for successful file upload response."""

    status = serializers.CharField(default="success")
    uploaded = UploadedFileSerializer(many=True)
    message = serializers.CharField()


class JobFileUploadPartialResponseSerializer(serializers.Serializer):
    """Serializer for partial success file upload response."""

    status = serializers.CharField()
    uploaded = UploadedFileSerializer(many=True)
    errors = serializers.ListField(child=serializers.CharField())


class JobFileErrorResponseSerializer(serializers.Serializer):
    """Serializer for error responses."""

    status = serializers.CharField(default="error")
    message = serializers.CharField()


class JobFileUpdateSuccessResponseSerializer(serializers.Serializer):
    """Serializer for successful file update response."""

    status = serializers.CharField(default="success")
    message = serializers.CharField()
    print_on_jobsheet = serializers.BooleanField()


class JobFileThumbnailErrorResponseSerializer(serializers.Serializer):
    """Serializer for thumbnail error response."""

    status = serializers.CharField(default="error")
    message = serializers.CharField()


class JobFileUploadViewResponseSerializer(serializers.Serializer):
    """Serializer for JobFileUploadView response."""

    status = serializers.CharField(default="success")
    uploaded = JobFileSerializer(many=True)
    message = serializers.CharField()
