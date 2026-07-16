import uuid
from collections.abc import Iterable

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.base import ModelBase
from encrypted_model_fields.fields import (
    EncryptedCharField,
)


class PhoneEndpoint(models.Model):
    """Phone number controlled by this company, including staff and PABX routes."""

    class EndpointType(models.TextChoices):
        MAIN_LINE = "main_line", "Main line"
        STAFF_MOBILE = "staff_mobile", "Staff mobile"
        STAFF_DDI = "staff_ddi", "Staff DDI"
        EXTENSION = "extension", "Extension"
        SHARED = "shared", "Shared"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    number = models.CharField(max_length=150)
    normalized_number = models.CharField(max_length=150, unique=True, db_index=True)
    label = models.CharField(max_length=255)
    endpoint_type = models.CharField(max_length=30, choices=EndpointType.choices)
    staff = models.ForeignKey(
        "accounts.Staff",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="phone_endpoints",
    )
    provider_account_code = models.CharField(max_length=100, blank=True)
    provider_metadata = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["endpoint_type", "label", "normalized_number"]
        indexes = [
            models.Index(
                fields=["is_active", "normalized_number"],
                name="crm_phone_endpoint_active_idx",
            ),
            models.Index(
                fields=["staff", "is_active"],
                name="crm_phone_endpoint_staff_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.label} ({self.normalized_number})"

    def save(
        self,
        *,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        from apps.company.models import ContactMethod

        self.normalized_number = ContactMethod.normalize_phone(self.number)
        if not self.normalized_number:
            raise ValueError("phone endpoint requires a phone number")
        if self.is_active and self._active_number_changed():
            # Mirror of the ContactMethod.save() guard: a number cannot be
            # both a company contact method and an active internal endpoint, or
            # the company's calls would silently reclassify as INTERNAL.
            conflict = ContactMethod.conflicting_company(self.normalized_number, set())
            if conflict:
                raise ValidationError(
                    f"phone number {self.normalized_number} already belongs to "
                    f"{conflict.owner_display_name()} and cannot be an active "
                    "internal phone endpoint"
                )
        super().save(
            force_insert=force_insert,
            force_update=force_update,
            using=using,
            update_fields=update_fields,
        )

    def _active_number_changed(self) -> bool:
        """True when the endpoint is new or its number/is_active changed.

        Grandfathers pre-existing rows (symmetry with the grandfathering in
        ContactMethod.check_phone_assignment): re-saving an existing
        endpoint without touching number or is_active must not start failing.
        """
        if self._state.adding:
            return True
        stored = (
            type(self)
            .objects.filter(pk=self.pk)
            .values("normalized_number", "is_active")
            .first()
        )
        if stored is None:
            return True
        return (
            stored["normalized_number"] != self.normalized_number
            or stored["is_active"] != self.is_active
        )


class PhoneProviderSettings(models.Model):
    """CRM phone-provider connection settings."""

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    downloads_enabled = models.BooleanField(default=False)
    recording_deletion_enabled = models.BooleanField(default=False)
    base_url = models.URLField(null=True, blank=True, default=None)
    username = EncryptedCharField(max_length=255, blank=True, null=True)
    password = EncryptedCharField(max_length=255, blank=True, null=True)
    account_code = models.CharField(max_length=100, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Phone Provider Settings"
        verbose_name_plural = "Phone Provider Settings"

    @classmethod
    def get_solo(cls) -> "PhoneProviderSettings":
        settings, _created = cls.objects.get_or_create(pk=1)
        return settings

    def __str__(self) -> str:
        return "phone provider settings"


class PhoneCallRecord(models.Model):
    """Call detail row imported from the phone provider portal."""

    class Direction(models.TextChoices):
        INBOUND = "inbound", "Inbound"
        OUTBOUND = "outbound", "Outbound"
        INTERNAL = "internal", "Internal"
        UNKNOWN = "unknown", "Unknown"

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
    normalized_origin = models.CharField(max_length=150, blank=True)
    normalized_destination = models.CharField(max_length=150, blank=True)
    direction = models.CharField(
        max_length=20,
        choices=Direction.choices,
        default=Direction.UNKNOWN,
        db_index=True,
    )
    our_number = models.CharField(max_length=150, blank=True)
    external_number = models.CharField(max_length=150, blank=True)
    origin_endpoint = models.ForeignKey(
        PhoneEndpoint,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="origin_phone_calls",
    )
    destination_endpoint = models.ForeignKey(
        PhoneEndpoint,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="destination_phone_calls",
    )
    duration_seconds = models.PositiveIntegerField(default=0)
    charge = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    company = models.ForeignKey(
        "company.Company",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="phone_calls",
    )
    person = models.ForeignKey(
        "company.Person",
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
                fields=["company", "-call_datetime"],
                name="crm_phone_company_call_idx",
            ),
            models.Index(
                fields=["person", "-call_datetime"],
                name="crm_phone_person_call_idx",
            ),
            models.Index(
                fields=["job", "-call_datetime"],
                name="crm_phone_job_call_idx",
            ),
            models.Index(
                fields=["direction", "-call_datetime"],
                name="crm_phone_direction_idx",
            ),
            models.Index(
                fields=["origin_endpoint", "-call_datetime"],
                name="crm_phone_origin_ep_idx",
            ),
            models.Index(
                fields=["destination_endpoint", "-call_datetime"],
                name="crm_phone_dest_ep_idx",
            ),
            models.Index(
                fields=["normalized_origin"],
                name="crm_phone_origin_norm_idx",
            ),
            models.Index(
                fields=["normalized_destination"],
                name="crm_phone_dest_norm_idx",
            ),
        ]

    def save(
        self,
        *,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        from apps.company.models import ContactMethod

        self.normalized_origin = ContactMethod.normalize_phone(self.origin)
        self.normalized_destination = ContactMethod.normalize_phone(self.destination)
        if update_fields is not None:
            fields = set(update_fields)
            if "origin" in fields:
                fields.add("normalized_origin")
            if "destination" in fields:
                fields.add("normalized_destination")
            update_fields = fields
        super().save(
            force_insert=force_insert,
            force_update=force_update,
            using=using,
            update_fields=update_fields,
        )

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
