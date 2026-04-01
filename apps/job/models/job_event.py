import hashlib
import uuid
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import models
from django.utils.timezone import now

from apps.accounts.models import Staff


class JobEvent(models.Model):
    # CHECKLIST - when adding a new field or property to JobEvent, check these locations:
    #   1. JOBEVENT_API_FIELDS or JOBEVENT_INTERNAL_FIELDS below (if it's a model field)
    #   2. JobEventSerializer in apps/job/serializers/job_serializer.py (uses JOBEVENT_API_FIELDS)
    #   3. _track_field_changes() in apps/job/models/job.py (creates JobEvent for field changes)
    #   4. _handle_status_change() in apps/job/models/job.py (creates JobEvent for status changes)
    #   5. create_job() in apps/job/services/job_rest_service.py (creates job_created event)
    #   6. _build_and_apply_delta() in apps/job/services/job_rest_service.py (creates job_updated event)
    #   7. create_job_event() in apps/job/services/job_rest_service.py (creates manual_note event)
    #   8. generate_delivery_docket() in apps/job/services/delivery_docket_service.py (creates event)
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
    description = models.TextField()
    schema_version = models.PositiveSmallIntegerField(default=0)
    change_id = models.UUIDField(null=True, blank=True)
    delta_before = models.JSONField(null=True, blank=True)
    delta_after = models.JSONField(null=True, blank=True)
    delta_meta = models.JSONField(null=True, blank=True)
    delta_checksum = models.CharField(max_length=128, blank=True, default="")

    # Field for deduplication hash
    dedup_hash = models.CharField(
        max_length=64,
        null=True,
        blank=True,
        help_text="MD5 hash for deduplication based on job+staff+description+type",
    )

    def __str__(self) -> str:
        return f"{self.timestamp}: {self.event_type} for {self.job.name if self.job else 'Unknown Job'}"

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
        components = [
            str(self.job_id) if self.job_id else "",
            str(self.staff_id) if self.staff_id else "",
            self.description.strip().lower(),
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
                existing_event = cls.objects.filter(
                    job=kwargs.get("job"),
                    staff=kwargs.get("staff"),
                    event_type=kwargs.get("event_type", "manual_note"),
                    description=kwargs.get("description", "").strip(),
                ).first()

                if existing_event:
                    return existing_event, False

            # Re-raise if not a duplicate error
            raise
