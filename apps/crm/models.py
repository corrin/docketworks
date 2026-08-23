"""Phone-provider CRM models.

v2.0 data migrates by pg_dump/restore, so column names and nullability stay
bit-identical to v1. That parity requirement is why ``null=True`` on string
fields is kept verbatim (``# noqa: DJ001`` at each site).

The phone provider's connection settings are columns on
``apps.core.models.IntegrationSettings`` (ADR 0053), not a model here.
"""

import uuid
from collections.abc import Iterable
from typing import ClassVar

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.base import ModelBase


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
    provider_account_code = models.CharField(  # noqa: DJ001
        max_length=100, blank=True, null=True
    )
    provider_metadata = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering: ClassVar[list[str]] = ["endpoint_type", "label", "normalized_number"]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(
                fields=["is_active", "normalized_number"],
                name="crm_phone_endpoint_active_idx",
            ),
            models.Index(
                fields=["staff", "is_active"],
                name="crm_phone_endpoint_staff_idx",
            ),
        ]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=~models.Q(provider_account_code=""),
                name="provider_account_code_not_blank",
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
        """Save, normalizing the number and guarding against company-number clashes."""
        from apps.company.models import ContactMethod  # noqa: PLC0415 -- company <-> crm cycle

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
        """Return True when the endpoint is new or its number/is_active changed.

        Grandfathers pre-existing rows (symmetry with the grandfathering in
        ContactMethod.check_phone_assignment): re-saving an existing
        endpoint without touching number or is_active must not start failing.
        """
        if self._state.adding:
            return True
        stored = (
            type(self).objects.filter(pk=self.pk).values("normalized_number", "is_active").first()
        )
        if stored is None:
            return True
        return (
            stored["normalized_number"] != self.normalized_number
            or stored["is_active"] != self.is_active
        )


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
    call_type = models.CharField(max_length=100, blank=True, null=True)  # noqa: DJ001
    status = models.CharField(max_length=100, blank=True, null=True)  # noqa: DJ001
    description = models.TextField(blank=True, null=True)  # noqa: DJ001
    origin = models.CharField(max_length=150, blank=True, null=True)  # noqa: DJ001
    destination = models.CharField(max_length=150, blank=True, null=True)  # noqa: DJ001
    normalized_origin = models.CharField(  # noqa: DJ001
        max_length=150, blank=True, null=True
    )
    normalized_destination = models.CharField(  # noqa: DJ001
        max_length=150, blank=True, null=True
    )
    direction = models.CharField(
        max_length=20,
        choices=Direction.choices,
        default=Direction.UNKNOWN,
        db_index=True,
    )
    our_number = models.CharField(max_length=150, blank=True, null=True)  # noqa: DJ001
    external_number = models.CharField(  # noqa: DJ001
        max_length=150, blank=True, null=True
    )
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
        ordering: ClassVar[list[str]] = ["-call_datetime"]
        indexes: ClassVar[list[models.Index]] = [
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
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(condition=~models.Q(call_type=""), name="call_type_not_blank"),
            models.CheckConstraint(
                condition=~models.Q(description=""),
                name="crm_phonecallrecord_description_not_blank",
            ),
            models.CheckConstraint(
                condition=~models.Q(destination=""), name="destination_not_blank"
            ),
            models.CheckConstraint(
                condition=~models.Q(external_number=""), name="external_number_not_blank"
            ),
            models.CheckConstraint(
                condition=~models.Q(normalized_destination=""),
                name="normalized_destination_not_blank",
            ),
            models.CheckConstraint(
                condition=~models.Q(normalized_origin=""), name="normalized_origin_not_blank"
            ),
            models.CheckConstraint(condition=~models.Q(origin=""), name="origin_not_blank"),
            models.CheckConstraint(condition=~models.Q(our_number=""), name="our_number_not_blank"),
            models.CheckConstraint(condition=~models.Q(status=""), name="status_not_blank"),
        ]

    def __str__(self) -> str:
        return f"{self.call_datetime:%Y-%m-%d %H:%M} {self.origin} -> {self.destination}"

    def save(
        self,
        *,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        """Save, refreshing the normalized origin/destination columns."""
        from apps.company.models import ContactMethod  # noqa: PLC0415 -- company <-> crm cycle

        # normalize_phone returns "" for "no number" because it also feeds
        # ContactMethod.normalized_value, which is NOT NULL. These columns are
        # nullable, so unset is NULL here.
        self.normalized_origin = ContactMethod.normalize_phone(self.origin) or None
        self.normalized_destination = ContactMethod.normalize_phone(self.destination) or None
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
    filename = models.CharField(max_length=255, blank=True, null=True)  # noqa: DJ001
    storage_path = models.CharField(max_length=500, blank=True, null=True)  # noqa: DJ001
    content_type = models.CharField(max_length=100, blank=True, null=True)  # noqa: DJ001
    byte_size = models.PositiveIntegerField(null=True, blank=True)
    # Measured from the audio when it is archived. Not the call's CDR
    # ``seconds``: the provider bills per started minute, so a 71-second
    # recording arrives as a 120-second call. Milliseconds, integer: a
    # measurement with no float and no Decimal on the wire. NULL is "no file".
    duration_ms = models.PositiveIntegerField(null=True, blank=True)
    sha256 = models.CharField(max_length=64, blank=True, null=True)  # noqa: DJ001
    archived_at = models.DateTimeField(null=True, blank=True, db_index=True)
    archive_error = models.TextField(blank=True, null=True)  # noqa: DJ001
    provider_deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)
    provider_delete_error = models.TextField(blank=True, null=True)  # noqa: DJ001
    local_deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering: ClassVar[list[str]] = ["-call__call_datetime"]
        indexes: ClassVar[list[models.Index]] = [
            models.Index(
                fields=["account_code", "archived_at"],
                name="crm_phone_rec_archive_idx",
            ),
            models.Index(
                fields=["provider_deleted_at", "archived_at"],
                name="crm_phone_rec_delete_idx",
            ),
        ]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=~models.Q(archive_error=""), name="archive_error_not_blank"
            ),
            models.CheckConstraint(
                condition=~models.Q(content_type=""), name="content_type_not_blank"
            ),
            models.CheckConstraint(condition=~models.Q(filename=""), name="filename_not_blank"),
            models.CheckConstraint(
                condition=~models.Q(provider_delete_error=""),
                name="provider_delete_error_not_blank",
            ),
            models.CheckConstraint(condition=~models.Q(sha256=""), name="sha256_not_blank"),
            models.CheckConstraint(
                condition=~models.Q(storage_path=""), name="storage_path_not_blank"
            ),
        ]

    def __str__(self) -> str:
        return f"phone call recording {self.provider_recording_id}"
