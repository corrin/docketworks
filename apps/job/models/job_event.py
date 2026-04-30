import hashlib
import uuid
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import models
from django.utils.timezone import now

from apps.accounts.models import Staff


def _truthy(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "1"}
    return bool(value)


def _truncate(text, max_chars: int = 60) -> str:
    if text is None or text == "":
        return ""
    text = str(text)
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def _format_ordinal(n: int) -> str:
    if 10 <= (n % 100) <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _format_status(slug: str) -> str:
    if not slug:
        return ""
    # Lazy import to avoid Job ↔ JobEvent circular at module load
    from apps.job.models.job import Job

    return dict(Job.JOB_STATUS_CHOICES).get(slug, slug.replace("_", " ").title())


def _truncate_change(label: str, old, new) -> str:
    return f"{label} changed from '{_truncate(old)}' to '{_truncate(new)}'"


def _quote_acceptance_descriptor(old, new) -> str:
    if new and not old:
        return f"Quote accepted on {new}"
    if old and not new:
        return "Quote acceptance cleared"
    return f"Quote acceptance date changed from {old} to {new}"


# Per-field descriptor: field_name (as it appears in detail.changes[].field_name)
# → callable(old, new) → str. Fields not listed here use _default_descriptor.
_FIELD_DESCRIPTORS = {
    "Rejected": lambda old, new: (
        "Job marked as rejected" if _truthy(new) else "Rejection cleared"
    ),
    "Complex job": lambda old, new: (
        "Marked as complex job" if _truthy(new) else "Unmarked as complex job"
    ),
    "Paid": lambda old, new: ("Marked as paid" if _truthy(new) else "Marked as unpaid"),
    "Collected": lambda old, new: (
        "Marked as collected" if _truthy(new) else "Marked as not collected"
    ),
    "Quote acceptance date": _quote_acceptance_descriptor,
    "Internal notes": lambda old, new: _truncate_change("Notes", old, new),
    "Job description": lambda old, new: _truncate_change("Description", old, new),
    "Notes": lambda old, new: _truncate_change("Notes", old, new),
    "Description": lambda old, new: _truncate_change("Description", old, new),
}


def _default_descriptor(field_name: str, old, new) -> str:
    return f"{field_name} changed from '{old}' to '{new}'"


def _render_change(change: dict) -> str:
    field = change.get("field_name", "")
    old = change.get("old_value", "")
    new = change.get("new_value", "")
    descriptor = _FIELD_DESCRIPTORS.get(field)
    if descriptor:
        return descriptor(old, new)
    return _default_descriptor(field, old, new)


class JobEvent(models.Model):
    # Field-change events are created automatically by Job.save() in
    # apps/job/models/job.py. All fields are tracked unless listed in
    # Job.UNTRACKED_FIELDS. Business-action events (Xero, delivery docket,
    # JSA, etc.) are created by their respective services.
    #
    # Database fields exposed via API serializers
    JOBEVENT_API_FIELDS = [
        "id",
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
        "description",
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
    staff = models.ForeignKey(Staff, on_delete=models.PROTECT)
    event_type = models.CharField(
        max_length=100, null=False, blank=False, default="automatic_event"
    )  # e.g., "status_change", "manual_note"
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

    @property
    def description(self) -> str:
        return self.build_description()

    def build_description(self) -> str:
        """Generate human-readable description from event_type + detail.

        Fallback chain:
          1. detail.legacy_description (preserved by migration 0077 for events that
             couldn't be parsed into structured data);
          2. dispatch to _DESCRIPTION_BUILDERS[event_type] if registered and the
             builder produces non-empty output;
          3. f"({event_type})" sentinel — should not fire post-migration.
        """
        detail = self.detail or {}
        legacy = detail.get("legacy_description")
        if legacy:
            return legacy

        builder = self._DESCRIPTION_BUILDERS.get(self.event_type)
        if builder:
            built = builder(detail)
            if built:
                return built

        return f"({self.event_type})"

    @staticmethod
    def _build_changes_description(detail: dict) -> str:
        changes = detail.get("changes", [])
        if not changes:
            return ""
        parts = [_render_change(change) for change in changes]
        return ". ".join(part for part in parts if part)

    @staticmethod
    def _build_priority_changed_description(detail: dict) -> str:
        """Friendly priority change description.

        With detail.position present (modern events): describe the rank move.
        Without (legacy ~38k rows): show direction only — historical column rank
        is unrecoverable from the float values alone.
        """
        position = detail.get("position") or {}
        if position:
            old_pos = position.get("old_position")
            new_pos = position.get("new_position")
            old_status = position.get("old_status")
            new_status = position.get("new_status")
            old_total = position.get("old_total")
            new_total = position.get("new_total")

            if old_status and new_status and old_status != new_status:
                old_label = _format_status(old_status)
                new_label = _format_status(new_status)
                return (
                    f"Moved from {old_label} ({_format_ordinal(old_pos)} of {old_total}) "
                    f"to {new_label} ({_format_ordinal(new_pos)} of {new_total})"
                )

            if new_pos == old_pos:
                # Defensive: no-op rank events should be suppressed at create
                # time (Job._record_change_event). Render nothing if one slips
                # through — falls through to the sentinel.
                return ""
            status_label = _format_status(new_status or old_status)
            total = new_total or old_total
            in_label = f" in {status_label}" if status_label else ""
            direction = "increased" if new_pos < old_pos else "decreased"
            return (
                f"Priority {direction} from {_format_ordinal(old_pos)} "
                f"to {_format_ordinal(new_pos)} of {total}{in_label}"
            )

        # Legacy fallback: direction only, from float comparison
        changes = detail.get("changes") or []
        if changes:
            change = changes[0]
            try:
                old = float(change.get("old_value"))
                new = float(change.get("new_value"))
            except (TypeError, ValueError):
                return "Priority changed"
            if abs(new - old) < 1e-6:
                return ""
            return "Priority increased" if new > old else "Priority decreased"
        return ""

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
        "priority_changed": _build_priority_changed_description.__func__,
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
        """Generate MD5 hash for deduplication of manual notes."""
        text = (self.detail or {}).get("note_text", "")
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
