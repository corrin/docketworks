import uuid

from django.db import models


class PhoneCallRecord(models.Model):
    """Call detail row imported from the phone provider portal."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider_call_id = models.CharField(max_length=255, unique=True)
    account_code = models.CharField(max_length=100)
    call_datetime = models.DateTimeField(db_index=True)
    call_date = models.DateField(db_index=True)
    call_time = models.TimeField()
    call_type = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=100, blank=True)
    description = models.TextField(blank=True)
    origin = models.CharField(max_length=150, blank=True)
    destination = models.CharField(max_length=150, blank=True)
    duration_seconds = models.PositiveIntegerField(default=0)
    charge = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    client = models.ForeignKey(
        "client.Client",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="phone_calls",
    )
    contact = models.ForeignKey(
        "client.ClientContact",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="phone_calls",
    )
    job = models.ForeignKey(
        "job.Job",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="phone_calls",
    )
    job_linked_at = models.DateTimeField(null=True, blank=True)
    job_linked_by = models.ForeignKey(
        "accounts.Staff",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="linked_phone_calls",
    )
    raw_json = models.JSONField()
    imported_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-call_datetime"]
        indexes = [
            models.Index(
                fields=["account_code", "-call_datetime"],
                name="crm_phone_acct_call_idx",
            ),
            models.Index(
                fields=["client", "-call_datetime"],
                name="crm_phone_client_call_idx",
            ),
            models.Index(
                fields=["contact", "-call_datetime"],
                name="crm_phone_contact_call_idx",
            ),
            models.Index(
                fields=["job", "-call_datetime"],
                name="crm_phone_job_call_idx",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"{self.call_datetime:%Y-%m-%d %H:%M} "
            f"{self.origin} -> {self.destination}"
        )


class PhoneCallRecording(models.Model):
    """Archived MP3 recording for a phone provider call."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    call = models.OneToOneField(
        PhoneCallRecord,
        on_delete=models.CASCADE,
        related_name="recording",
    )
    provider_recording_id = models.CharField(max_length=255, unique=True)
    account_code = models.CharField(max_length=100)
    filename = models.CharField(max_length=255, blank=True)
    storage_path = models.CharField(max_length=500, blank=True)
    content_type = models.CharField(max_length=100, blank=True)
    byte_size = models.PositiveIntegerField(null=True, blank=True)
    sha256 = models.CharField(max_length=64, blank=True)
    archived_at = models.DateTimeField(null=True, blank=True, db_index=True)
    archive_error = models.TextField(blank=True)
    provider_deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)
    provider_delete_error = models.TextField(blank=True)
    local_deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-call__call_datetime"]
        indexes = [
            models.Index(
                fields=["account_code", "archived_at"],
                name="crm_phone_rec_archive_idx",
            ),
            models.Index(
                fields=["provider_deleted_at", "archived_at"],
                name="crm_phone_rec_delete_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"phone call recording {self.provider_recording_id}"
