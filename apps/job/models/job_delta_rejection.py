import uuid

from django.db import models
from django.utils import timezone

from apps.accounts.models import Staff


class JobDeltaRejection(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.ForeignKey(
        "job.Job",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="delta_rejections",
    )
    staff = models.ForeignKey(
        Staff,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="delta_rejections",
    )
    change_id = models.UUIDField(null=True, blank=True, db_index=True)
    reason = models.CharField(max_length=255)
    detail = models.TextField(blank=True)
    envelope = models.JSONField()
    checksum = models.CharField(max_length=128, blank=True)
    request_etag = models.CharField(max_length=128, blank=True)
    request_ip = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(
                fields=["change_id", "-created_at"],
                name="job_delta_rej_change_idx",
            ),
            models.Index(fields=["-created_at"], name="job_delta_rej_created_idx"),
        ]

    def __str__(self) -> str:  # pragma: no cover
        job_part = str(self.job_id) if self.job_id else "unknown-job"
        change_part = str(self.change_id) if self.change_id else "no-change-id"
        return f"Delta rejection {self.id} ({job_part} / {change_part})"
