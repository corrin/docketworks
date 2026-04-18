import logging
import uuid

from django.db import models
from django.utils import timezone


class AppError(models.Model):
    """Persistent record of an application error."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    timestamp = models.DateTimeField(auto_now_add=True)
    message = models.TextField()
    data = models.JSONField(blank=True, null=True)

    # Code location fields for filtering
    app = models.CharField(max_length=50, blank=True, null=True)
    file = models.CharField(max_length=200, blank=True, null=True)
    function = models.CharField(max_length=100, blank=True, null=True)
    severity = models.IntegerField(default=logging.ERROR)

    # Commonly filtered business context (separate fields)
    job_id = models.UUIDField(blank=True, null=True)
    user_id = models.UUIDField(blank=True, null=True)

    # Error resolution tracking
    resolved = models.BooleanField(default=False)
    resolved_by = models.ForeignKey(
        "accounts.Staff", on_delete=models.PROTECT, blank=True, null=True
    )
    resolved_timestamp = models.DateTimeField(blank=True, null=True)

    def mark_resolved(self, staff_member):
        """Mark this error as resolved by the given staff member."""
        self.resolved = True
        self.resolved_by = staff_member
        self.resolved_timestamp = timezone.now()
        self.save()

    def mark_unresolved(self, staff_member):
        """Remove the resolved flag."""
        self.resolved = False
        self.resolved_by = None
        self.resolved_timestamp = None
        self.save()

    class Meta:
        ordering = ["-timestamp"]
        verbose_name = "Application Error"
        verbose_name_plural = "Application Errors"
        indexes = [
            models.Index(
                fields=["timestamp", "severity"]
            ),  # Common: recent errors by severity
            models.Index(
                fields=["resolved", "timestamp"]
            ),  # Common: unresolved errors chronologically
            models.Index(fields=["app", "severity"]),  # Common: errors by app section
            models.Index(
                fields=["resolved", "message"], name="app_error_resolved_msg_idx"
            ),
        ]


class XeroError(AppError):
    """Specialised error raised during Xero synchronisation."""

    entity = models.CharField(max_length=100)
    reference_id = models.CharField(max_length=255)
    kind = models.CharField(max_length=50)

    class Meta:
        verbose_name = "Xero Error"
        verbose_name_plural = "Xero Errors"
