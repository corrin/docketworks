"""The JobEvent model: the append-only audit trail for job changes."""

import hashlib
from collections.abc import Callable
from datetime import timedelta
from typing import Any, ClassVar, TypedDict

from django.core.exceptions import ValidationError
from django.db import models
from django.utils.timezone import now

from apps.core.audit import AuditDetail, AuditEvent, JsonScalar, truncate_change


class PositionDetail(TypedDict, total=False):
    """A priority or status move's rank facts, as ``detail.position`` records them."""

    old_position: int
    new_position: int
    old_status: str
    new_status: str
    old_total: int
    new_total: int


class JobEventDetail(AuditDetail, total=False):
    """Every key a job event's builders read from ``detail``."""

    job_name: str
    company_name: str
    person_name: str
    initial_status: str
    pricing_methodology: str
    position: PositionDetail
    xero_invoice_number: str
    old_total_excl_tax: str
    new_total_excl_tax: str
    xero_quote_number: str
    filename: str
    jsa_title: str


def _truthy(value: JsonScalar) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "1"}
    return bool(value)


def _format_ordinal(n: int | None) -> str:
    if n is None:
        # Corrupt position payloads are invalid rather than silently repairable.
        raise TypeError("ordinal position missing from event detail")
    suffix = "th" if 10 <= (n % 100) <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _format_status(slug: str | None) -> str:
    if not slug:
        return ""
    # Lazy import to avoid Job ↔ JobEvent circular at module load
    from apps.job.models.job import Job  # noqa: PLC0415

    return dict(Job.JOB_STATUS_CHOICES).get(slug, slug.replace("_", " ").title())


def _completion_confirmation_descriptor(
    confirmed: str, withdrawn: str
) -> Callable[[JsonScalar, JsonScalar], str]:
    """Descriptor factory for front-desk checklist items.

    Both wordings are given explicitly rather than built from one subject: an
    unticking is the change most worth finding later, so it earns a sentence that
    reads properly instead of a negated one that does not.
    """

    def descriptor(old: JsonScalar, new: JsonScalar) -> str:  # noqa: ARG001 -- (old, new) callback protocol
        if _truthy(new):
            return confirmed
        return withdrawn

    return descriptor


def _quote_acceptance_descriptor(old: JsonScalar, new: JsonScalar) -> str:
    if new and not old:
        return f"Quote accepted on {new}"
    if old and not new:
        return "Quote acceptance cleared"
    return f"Quote acceptance date changed from {old} to {new}"


# Per-field descriptor: field_name (as it appears in detail.changes[].field_name)
# → callable(old, new) → str. Fields not listed here use the base's default sentence.
_FIELD_DESCRIPTORS: dict[str, Callable[[JsonScalar, JsonScalar], str]] = {
    "Rejected": lambda old, new: (  # noqa: ARG005 -- (old, new) callback protocol
        "Job marked as rejected" if _truthy(new) else "Rejection cleared"
    ),
    "Complex job": lambda old, new: (  # noqa: ARG005 -- (old, new) callback protocol
        "Marked as complex job" if _truthy(new) else "Unmarked as complex job"
    ),
    "Paid": lambda old, new: (  # noqa: ARG005 -- (old, new) callback protocol
        "Marked as paid" if _truthy(new) else "Marked as unpaid"
    ),
    "Quote acceptance date": _quote_acceptance_descriptor,
    "Foreman sign-off": _completion_confirmation_descriptor(
        "Foreman signed the job off", "Foreman sign-off withdrawn"
    ),
    "Timesheets collected": _completion_confirmation_descriptor(
        "Timesheets collected from the workshop", "Timesheet collection unconfirmed"
    ),
    "Materials checked": _completion_confirmation_descriptor(
        "Materials checked on the job", "Materials check unconfirmed"
    ),
    "Customer called": _completion_confirmation_descriptor(
        "Customer called", "Customer call unconfirmed"
    ),
    "Job released": _completion_confirmation_descriptor("Job released", "Job release withdrawn"),
    "Internal notes": lambda old, new: truncate_change("Notes", old, new),
    "Job description": lambda old, new: truncate_change("Description", old, new),
    "Notes": lambda old, new: truncate_change("Notes", old, new),
    "Description": lambda old, new: truncate_change("Description", old, new),
}


class JobEvent(AuditEvent):
    """One audit event on a job: a field change, status move, or business action."""

    # Field-change events are created automatically by Job.save() in
    # apps/job/models/job.py. All fields are tracked unless listed in
    # Job.UNTRACKED_FIELDS. Business-action events (Xero, delivery docket,
    # JSA, etc.) are created by their respective services.
    #
    # Database fields exposed via API serializers
    JOBEVENT_API_FIELDS: ClassVar[list[str]] = [
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
    JOBEVENT_API_PROPERTIES: ClassVar[list[str]] = [
        "description",
        "can_undo",
        "undo_description",
    ]

    # Internal fields not exposed in API
    JOBEVENT_INTERNAL_FIELDS: ClassVar[list[str]] = [
        "job",
        "dedup_hash",
    ]

    # All JobEvent model fields (derived)
    JOBEVENT_ALL_FIELDS: ClassVar[list[str]] = JOBEVENT_API_FIELDS + JOBEVENT_INTERNAL_FIELDS

    job = models.ForeignKey(
        "Job", on_delete=models.CASCADE, related_name="events", null=True, blank=True
    )
    # Redeclared over the base: job events predate the base and their rows
    # carry this default, so the column keeps it.
    event_type = models.CharField(
        max_length=100, null=False, blank=False, default="automatic_event"
    )  # e.g., "status_change", "manual_note"
    schema_version = models.PositiveSmallIntegerField(default=0)
    change_id = models.UUIDField(null=True, blank=True)
    delta_meta = models.JSONField(null=True, blank=True)
    delta_checksum = models.CharField(max_length=128, blank=True, null=True)  # noqa: DJ001 -- restored column retains nullable storage

    detail = models.JSONField(
        default=dict,
        blank=True,
        help_text="Structured audit data for this event. Keys vary by event_type.",
    )

    # Field for deduplication hash
    dedup_hash = models.CharField(  # noqa: DJ001 -- restored column retains nullable storage
        max_length=64,
        null=True,
        blank=True,
        help_text="MD5 hash for deduplication based on job+staff+description+type",
    )

    class Meta(AuditEvent.Meta):
        # Database constraints for preventing duplicates
        constraints: ClassVar[list[models.BaseConstraint]] = [
            # Prevent duplicate manual events by same user on same job
            models.UniqueConstraint(
                fields=["job", "staff", "event_type", "dedup_hash"],
                name="unique_manual_event_per_user_job",
            ),
            models.CheckConstraint(condition=~models.Q(dedup_hash=""), name="dedup_hash_not_blank"),
            models.CheckConstraint(
                condition=~models.Q(delta_checksum=""), name="delta_checksum_not_blank"
            ),
        ]

        # Optimized indexes
        indexes: ClassVar[list[models.Index]] = [
            models.Index(fields=["job", "-timestamp"], name="jobevent_job_timestamp_idx"),
            models.Index(fields=["event_type", "-timestamp"], name="jobevent_type_timestamp_idx"),
            models.Index(fields=["staff", "-timestamp"], name="jobevent_staff_timestamp_idx"),
            models.Index(fields=["dedup_hash"], name="jobevent_dedup_hash_idx"),
            models.Index(fields=["change_id"], name="jobevent_change_idx"),
        ]

    def __str__(self) -> str:
        return (
            f"{self.timestamp}: {self.event_type} "
            f"for {self.job.name if self.job else 'Unknown Job'}"
        )

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Override save with validation."""
        # Run validation
        self.full_clean()

        # Generate hash if needed
        if self.event_type == "manual_note" and not self.dedup_hash:
            self.dedup_hash = self._generate_dedup_hash()

        super().save(*args, **kwargs)

    def clean(self) -> None:
        """Run custom validation to prevent duplicates."""
        super().clean()

        # Generate hash for manual events
        if self.event_type == "manual_note":
            self.dedup_hash = self._generate_dedup_hash()

            # Check for recent duplicates (within 5 seconds)
            if self._check_recent_duplicate():
                raise ValidationError(
                    "A similar manual event was created recently. "
                    "Please wait before adding another."
                )

    def build_description(self) -> str:
        """Render a registered builder's own kind of detail, else what the base renders."""
        detail: JobEventDetail = self.detail
        builder = self.DESCRIPTION_BUILDERS.get(self.event_type)
        if builder:
            built = builder(detail)
            if built:
                return built
        return super().build_description()

    @staticmethod
    def _build_changes_description(detail: JobEventDetail) -> str:
        # Bound at call time so the base's renderer sees JobEvent's descriptors;
        # a bare name in the class body does not resolve to the inherited classmethod.
        return JobEvent.build_changes_description(detail)

    @staticmethod
    def _build_priority_changed_description(detail: JobEventDetail) -> str:  # noqa: PLR0911 -- Each event detail shape has an explicit rendering branch.
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
            if old_pos is None or new_pos is None:
                # Corrupt position payloads are invalid rather than silently repairable.
                raise TypeError("priority position missing from event detail")
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
                old = float(str(change.get("old_value")))
                new = float(str(change.get("new_value")))
            # deliberate-swallow: this builds one human-readable line of the job
            # timeline from a legacy event whose priority was free text. Raising
            # would take out the entire timeline view over a single old row, so
            # the direction is dropped and the fact of the change is kept.
            except (TypeError, ValueError):
                return "Priority changed"
            if abs(new - old) < 1e-6:
                return ""
            return "Priority increased" if new > old else "Priority decreased"
        return ""

    @staticmethod
    def _build_status_changed_description(detail: JobEventDetail) -> str:
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

        return JobEvent._build_changes_description(detail)

    @staticmethod
    def _build_job_created_description(detail: JobEventDetail) -> str:
        # Fallback for creations written before 2026-04-22, the last date a job
        # event was recorded without these fields; every creation since carries
        # all five. A job's initial status and pricing methodology cannot be
        # recovered — the job now holds whatever it was last changed to, not
        # what it started as — so the sentence names what is missing instead of
        # quietly dropping it. Printing "Unknown" was the previous behaviour and
        # is rejected: it asserts the absence as a value, so the line reads as a
        # job genuinely created for a company called Unknown.
        job_name = detail.get("job_name")
        company_name = detail.get("company_name")
        person_name = detail.get("person_name")
        initial_status = detail.get("initial_status")
        pricing = detail.get("pricing_methodology")

        subject = f"New job '{job_name}'" if job_name else "New job"
        if company_name:
            subject += f" created for company {company_name}"
        else:
            subject += " created"
        if person_name:
            subject += f" (Person: {person_name})"

        sentences = [subject]
        if initial_status:
            sentences.append(f"Initial status: {initial_status}")
        if pricing:
            sentences.append(f"Pricing methodology: {pricing}")
        if not (initial_status and pricing):
            sentences.append("Some creation details lost")
        return ". ".join(sentences) + "."

    @staticmethod
    def _build_invoice_created_description(detail: JobEventDetail) -> str:
        number = detail.get("xero_invoice_number", "Unknown")
        return f"Invoice {number} created in Xero"

    @staticmethod
    def _build_invoice_deleted_description(detail: JobEventDetail) -> str:
        number = detail.get("xero_invoice_number")
        if number:
            return f"Invoice {number} deleted from Xero"
        return "Invoice deleted from Xero"

    @staticmethod
    def _build_invoice_amount_changed_description(detail: JobEventDetail) -> str:
        number = detail.get("xero_invoice_number")
        old_total = detail.get("old_total_excl_tax")
        new_total = detail.get("new_total_excl_tax")
        subject = f"Invoice {number}" if number else "Invoice"
        return f"{subject} changed from ${old_total} to ${new_total} excluding tax"

    @staticmethod
    def _build_invoice_voided_description(detail: JobEventDetail) -> str:
        number = detail.get("xero_invoice_number")
        return f"Invoice {number} voided in Xero" if number else "Invoice voided in Xero"

    @staticmethod
    def _build_quote_created_description(detail: JobEventDetail) -> str:
        number = detail.get("xero_quote_number")
        if number:
            return f"Quote {number} created in Xero"
        return "Quote created in Xero"

    @staticmethod
    def _build_quote_deleted_description(detail: JobEventDetail) -> str:
        number = detail.get("xero_quote_number")
        if number:
            return f"Quote {number} deleted from Xero"
        return "Quote deleted from Xero"

    @staticmethod
    def _build_delivery_docket_description(detail: JobEventDetail) -> str:
        filename = detail.get("filename", "Unknown")
        return f"Delivery docket generated: {filename}"

    @staticmethod
    def _build_jsa_description(detail: JobEventDetail) -> str:
        title = detail.get("jsa_title", "Unknown")
        return f"JSA generated: {title}"

    FIELD_DESCRIPTORS = _FIELD_DESCRIPTORS

    # Every event type a writer records is registered here: the sentinel the
    # base falls through to is for a type nobody writes
    # (test_no_written_event_type_falls_through_to_the_sentinel).
    DESCRIPTION_BUILDERS: ClassVar[dict[str, Callable[[JobEventDetail], str]]] = {
        "job_created": _build_job_created_description,
        "status_changed": _build_status_changed_description,
        "job_updated": _build_changes_description,
        "company_changed": _build_changes_description,
        "person_changed": _build_changes_description,
        "notes_updated": _build_changes_description,
        "delivery_date_changed": _build_changes_description,
        "quote_accepted": _build_changes_description,
        "pricing_changed": _build_changes_description,
        "priority_changed": _build_priority_changed_description,
        "payment_received": _build_changes_description,
        "payment_updated": _build_changes_description,
        "job_collected": _build_changes_description,
        "collection_updated": _build_changes_description,
        "job_rejected": _build_changes_description,
        "completion_checklist_updated": _build_changes_description,
        "manual_note": AuditEvent.manual_note_description,
        "invoice_created": _build_invoice_created_description,
        "invoice_deleted": _build_invoice_deleted_description,
        "invoice_amount_changed": _build_invoice_amount_changed_description,
        "invoice_voided": _build_invoice_voided_description,
        "urgent_flagged": _build_changes_description,
        "urgent_cleared": _build_changes_description,
        "quote_created": _build_quote_created_description,
        "quote_deleted": _build_quote_deleted_description,
        "delivery_docket_generated": _build_delivery_docket_description,
        "jsa_generated": _build_jsa_description,
    }

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
        return hashlib.md5(hash_input).hexdigest()  # noqa: S324 -- Non-cryptographic deduplication key.

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
    def create_safe(cls, **kwargs: Any) -> "tuple[JobEvent, bool]":
        """Create a JobEvent, absorbing duplicate manual notes.

        Returns:
            tuple: (JobEvent instance, bool created)
        """
        try:
            event = cls(**kwargs)
            event.save()
            return event, True  # noqa: TRY300 -- The successful transaction returns its created event.

        # deliberate-swallow: a duplicate manual note is absorbed, not reported —
        # two people typing the same note (or one double-submitting) should get
        # the note that already exists rather than a validation error about
        # their own colleague. Any OTHER ValidationError still re-raises below.
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
