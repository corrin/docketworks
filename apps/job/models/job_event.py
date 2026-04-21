import hashlib
import uuid
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import models
from django.utils.timezone import now

from apps.accounts.models import Staff


class JobEvent(models.Model):
    # Field-change events are created automatically by Job.save() in
    # apps/job/models/job.py. All fields are tracked unless listed in
    # Job.UNTRACKED_FIELDS. Business-action events (Xero, delivery docket,
    # JSA, etc.) are created by their respective services.
    #
    # Database fields exposed via API serializers
    JOBEVENT_API_FIELDS = [
        "id",
        "description",
        "timestamp",
        "staff",
        "event_type",
        "schema_version",
        "change_id",
        "delta_before",
        "delta_after",
        "delta_meta",
        "delta_checksum",
        "detail",
    ]

    # Computed properties exposed via API serializers
    JOBEVENT_API_PROPERTIES = [
        "can_undo",
        "undo_description",
    ]

    # Internal fields not exposed in API
    JOBEVENT_INTERNAL_FIELDS = [
        "job",
        "dedup_hash",
    ]

    # All JobEvent model fields (derived)
    JOBEVENT_ALL_FIELDS = JOBEVENT_API_FIELDS + JOBEVENT_INTERNAL_FIELDS

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    job = models.ForeignKey(
        "Job", on_delete=models.CASCADE, related_name="events", null=True, blank=True
    )
    timestamp = models.DateTimeField(default=now)
    staff = models.ForeignKey(Staff, on_delete=models.PROTECT, null=True, blank=True)
    event_type = models.CharField(
        max_length=100, null=False, blank=False, default="automatic_event"
    )  # e.g., "status_change", "manual_note"
    description = models.TextField(blank=True, default="")
    schema_version = models.PositiveSmallIntegerField(default=0)
    change_id = models.UUIDField(null=True, blank=True)
    delta_before = models.JSONField(null=True, blank=True)
    delta_after = models.JSONField(null=True, blank=True)
    delta_meta = models.JSONField(null=True, blank=True)
    delta_checksum = models.CharField(max_length=128, blank=True, default="")

    detail = models.JSONField(
        default=dict,
        blank=True,
        help_text="Structured audit data for this event. Keys vary by event_type.",
    )

    # Field for deduplication hash
    dedup_hash = models.CharField(
        max_length=64,
        null=True,
        blank=True,
        help_text="MD5 hash for deduplication based on job+staff+description+type",
    )

    def __str__(self) -> str:
        return f"{self.timestamp}: {self.event_type} for {self.job.name if self.job else 'Unknown Job'}"

    def build_description(self) -> str:
        """Generate human-readable description from event_type + detail.

        Falls back to stored description for pre-migration rows where detail is empty.
        Returns legacy_description directly for backfilled rows that couldn't be
        fully parsed into structured data.
        """
        if not self.detail:
            return self.description

        if "legacy_description" in self.detail:
            return self.detail["legacy_description"]

        builder = self._DESCRIPTION_BUILDERS.get(self.event_type)
        if not builder:
            return self.description

        return builder(self.detail)

    @staticmethod
    def _build_changes_description(detail: dict) -> str:
        """Build description from a changes list (Job.save() events)."""
        changes = detail.get("changes", [])
        if not changes:
            return ""
        parts = []
        for change in changes:
            field = change["field_name"]
            old = change["old_value"]
            new = change["new_value"]
            parts.append(f"{field} changed from '{old}' to '{new}'")
        return ". ".join(parts)

    @staticmethod
    def _build_job_created_description(detail: dict) -> str:
        job_name = detail.get("job_name", "Unknown")
        client_name = detail.get("client_name", "Unknown")
        contact_name = detail.get("contact_name")
        initial_status = detail.get("initial_status", "Unknown")
        pricing = detail.get("pricing_methodology", "Unknown")
        contact_info = f" (Contact: {contact_name})" if contact_name else ""
        return (
            f"New job '{job_name}' created for client {client_name}{contact_info}. "
            f"Initial status: {initial_status}. "
            f"Pricing methodology: {pricing}."
        )

    @staticmethod
    def _build_manual_note_description(detail: dict) -> str:
        return detail.get("note_text", "")

    @staticmethod
    def _build_invoice_created_description(detail: dict) -> str:
        number = detail.get("xero_invoice_number", "Unknown")
        return f"Invoice {number} created in Xero"

    @staticmethod
    def _build_invoice_deleted_description(detail: dict) -> str:
        number = detail.get("xero_invoice_number")
        if number:
            return f"Invoice {number} deleted from Xero"
        return "Invoice deleted from Xero"

    @staticmethod
    def _build_quote_created_description(detail: dict) -> str:
        number = detail.get("xero_quote_number")
        if number:
            return f"Quote {number} created in Xero"
        return "Quote created in Xero"

    @staticmethod
    def _build_quote_deleted_description(detail: dict) -> str:
        number = detail.get("xero_quote_number")
        if number:
            return f"Quote {number} deleted from Xero"
        return "Quote deleted from Xero"

    @staticmethod
    def _build_delivery_docket_description(detail: dict) -> str:
        filename = detail.get("filename", "Unknown")
        return f"Delivery docket generated: {filename}"

    @staticmethod
    def _build_jsa_description(detail: dict) -> str:
        title = detail.get("jsa_title", "Unknown")
        return f"JSA generated: {title}"

    _DESCRIPTION_BUILDERS = {
        "job_created": _build_job_created_description.__func__,
        "status_changed": _build_changes_description.__func__,
        "job_updated": _build_changes_description.__func__,
        "client_changed": _build_changes_description.__func__,
        "contact_changed": _build_changes_description.__func__,
        "notes_updated": _build_changes_description.__func__,
        "delivery_date_changed": _build_changes_description.__func__,
        "quote_accepted": _build_changes_description.__func__,
        "pricing_changed": _build_changes_description.__func__,
        "priority_changed": _build_changes_description.__func__,
        "payment_received": _build_changes_description.__func__,
        "payment_updated": _build_changes_description.__func__,
        "job_collected": _build_changes_description.__func__,
        "collection_updated": _build_changes_description.__func__,
        "job_rejected": _build_changes_description.__func__,
        "manual_note": _build_manual_note_description.__func__,
        "invoice_created": _build_invoice_created_description.__func__,
        "invoice_deleted": _build_invoice_deleted_description.__func__,
        "quote_created": _build_quote_created_description.__func__,
        "quote_deleted": _build_quote_deleted_description.__func__,
        "delivery_docket_generated": _build_delivery_docket_description.__func__,
        "jsa_generated": _build_jsa_description.__func__,
    }

    class Meta:
        ordering = ["-timestamp"]

        # Database constraints for preventing duplicates
        constraints = [
            # Prevent duplicate manual events by same user on same job
            models.UniqueConstraint(
                fields=["job", "staff", "event_type", "dedup_hash"],
                name="unique_manual_event_per_user_job",
            ),
        ]

        # Optimized indexes
        indexes = [
            models.Index(
                fields=["job", "-timestamp"], name="jobevent_job_timestamp_idx"
            ),
            models.Index(
                fields=["event_type", "-timestamp"], name="jobevent_type_timestamp_idx"
            ),
            models.Index(
                fields=["staff", "-timestamp"], name="jobevent_staff_timestamp_idx"
            ),
            models.Index(fields=["dedup_hash"], name="jobevent_dedup_hash_idx"),
            models.Index(fields=["change_id"], name="jobevent_change_idx"),
        ]

    def clean(self):
        """Custom validation to prevent duplicates."""
        super().clean()

        # Generate hash for manual events
        if self.event_type == "manual_note":
            self.dedup_hash = self._generate_dedup_hash()

            # Check for recent duplicates (within 5 seconds)
            if self._check_recent_duplicate():
                raise ValidationError(
                    "A similar manual event was created recently. Please wait before adding another."
                )

    def save(self, *args, **kwargs):
        """Override save with validation."""
        # Run validation
        self.full_clean()

        # Generate hash if needed
        if self.event_type == "manual_note" and not self.dedup_hash:
            self.dedup_hash = self._generate_dedup_hash()

        super().save(*args, **kwargs)

    def _generate_dedup_hash(self) -> str:
        """Generate MD5 hash for deduplication."""
        text = self.detail.get("note_text", "") if self.detail else self.description
        components = [
            str(self.job_id) if self.job_id else "",
            str(self.staff_id) if self.staff_id else "",
            text.strip().lower(),
            self.event_type,
        ]

        hash_input = "|".join(components).encode("utf-8")
        return hashlib.md5(hash_input).hexdigest()

    def _check_recent_duplicate(self) -> bool:
        """Check if a similar event was created recently."""
        if not self.dedup_hash:
            return False

        # Check for events in the last 5 seconds
        recent_threshold = now() - timedelta(seconds=5)

        queryset = JobEvent.objects.filter(
            job=self.job,
            staff=self.staff,
            event_type="manual_note",
            dedup_hash=self.dedup_hash,
            timestamp__gte=recent_threshold,
        )

        # Exclude current event if updating
        if self.pk:
            queryset = queryset.exclude(pk=self.pk)

        return queryset.exists()

    @classmethod
    def create_safe(cls, **kwargs):
        """
        Safe creation method that prevents duplicates.

        Returns:
            tuple: (JobEvent instance, bool created)
        """
        try:
            event = cls(**kwargs)
            event.save()
            return event, True

        except ValidationError as e:
            # If duplicate error, try to find existing event
            if "similar manual event" in str(e).lower():
                detail = kwargs.get("detail", {})
                note_text = detail.get("note_text", "").strip() if detail else ""
                existing_event = cls.objects.filter(
                    job=kwargs.get("job"),
                    staff=kwargs.get("staff"),
                    event_type=kwargs.get("event_type", "manual_note"),
                    detail__note_text=note_text,
                ).first()

                if existing_event:
                    return existing_event, False

            # Re-raise if not a duplicate error
            raise
