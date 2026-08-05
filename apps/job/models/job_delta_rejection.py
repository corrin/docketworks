"""The JobDeltaRejection model: an audit row for rejected job delta envelopes."""

import uuid
from typing import TYPE_CHECKING, ClassVar

from django.db import models
from django.utils import timezone

if TYPE_CHECKING:
    from apps.accounts.models import Staff


class JobDeltaRejection(models.Model):
    """A rejected job change envelope, kept for observability and replay."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.ForeignKey(
        "job.Job",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="delta_rejections",
    )
    staff = models.ForeignKey(
        "accounts.Staff",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="delta_rejections",
    )
    change_id = models.UUIDField(null=True, blank=True, db_index=True)
    reason = models.CharField(max_length=255)
    detail = models.TextField(blank=True, null=True)  # noqa: DJ001 -- restored column retains nullable storage
    envelope = models.JSONField()
    checksum = models.CharField(max_length=128, blank=True, null=True)  # noqa: DJ001 -- restored column retains nullable storage
    request_etag = models.CharField(max_length=128, blank=True, null=True)  # noqa: DJ001 -- restored column retains nullable storage
    request_ip = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    resolved = models.BooleanField(default=False)
    resolved_by = models.ForeignKey(
        "accounts.Staff",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="resolved_delta_rejections",
    )
    resolved_timestamp = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)
        indexes: ClassVar[list[models.Index]] = [
            models.Index(
                fields=["change_id", "-created_at"],
                name="job_delta_rej_change_idx",
            ),
            models.Index(fields=["-created_at"], name="job_delta_rej_created_idx"),
            models.Index(fields=["resolved", "reason"], name="job_delta_rej_res_rsn_idx"),
        ]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(condition=~models.Q(checksum=""), name="checksum_not_blank"),
            models.CheckConstraint(condition=~models.Q(detail=""), name="detail_not_blank"),
            models.CheckConstraint(
                condition=~models.Q(request_etag=""), name="request_etag_not_blank"
            ),
        ]

    def __str__(self) -> str:  # pragma: no cover
        job_part = str(self.job_id) if self.job_id else "unknown-job"
        change_part = str(self.change_id) if self.change_id else "no-change-id"
        return f"Delta rejection {self.id} ({job_part} / {change_part})"

    def mark_resolved(self, staff_member: "Staff") -> None:
        """Mark this rejection as resolved by the given staff member."""
        self.resolved = True
        self.resolved_by = staff_member
        self.resolved_timestamp = timezone.now()
        self.save(update_fields=["resolved", "resolved_by", "resolved_timestamp"])

    def mark_unresolved(self, staff_member: "Staff") -> None:  # noqa: ARG002 -- Actor parameter keeps resolve/reopen calls symmetric.
        """Clear the resolved state of this rejection."""
        self.resolved = False
        self.resolved_by = None
        self.resolved_timestamp = None
        self.save(update_fields=["resolved", "resolved_by", "resolved_timestamp"])
