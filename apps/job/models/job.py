import logging
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Dict, List, Optional

from django.db import models, transaction
from django.db.models import Index, Max, Min
from django.utils import timezone
from simple_history.models import HistoricalRecords

from apps.accounts.models import Staff
from apps.client.models import Client
from apps.job.enums import RDTIType, SpeedQualityTradeoff
from apps.workflow.models import CompanyDefaults, XeroPayItem

from .costing import CostSet
from .job_event import JobEvent

logger = logging.getLogger(__name__)


def _json_safe(value):
    """Convert a model field value to a JSON-serializable form."""
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "__str__") and not isinstance(value, (str, int, float, bool)):
        return str(value)
    return value


class JobQuerySet(models.QuerySet):
    """Custom QuerySet that prevents .update() on tracked fields.

    All Job field changes must go through Job.save(staff=...) so that
    JobEvents are created automatically. Attempting to .update() a tracked
    field raises RuntimeError at dev time. For migrations or bookkeeping
    fields, use .untracked_update().
    """

    def create(self, **kwargs):
        """Create a Job, routing through save(staff=...) like every other path.

        Job.save() requires staff, so Manager.create()'s default implementation
        (which calls save() with no kwargs) would always raise. This override
        pops the staff kwarg and threads it through.
        """
        if "staff" not in kwargs:
            raise TypeError(
                "Job.objects.create() requires staff=... "
                "(routes through Job.save(staff=...))"
            )
        staff = kwargs.pop("staff")
        obj = self.model(**kwargs)
        self._for_write = True
        obj.save(staff=staff, using=self.db)
        return obj

    def update(self, **kwargs):
        tracked = set(kwargs.keys()) - Job.UNTRACKED_FIELDS
        if tracked:
            raise RuntimeError(
                f"Cannot .update() tracked fields {tracked}. "
                f"Use save(staff=...) so JobEvents are created. "
                f"For migrations or bookkeeping, use .untracked_update()."
            )
        return super().update(**kwargs)

    def untracked_update(self, **kwargs):
        """Bypass the tracked-field guard. Use only for migrations and
        bookkeeping fields that are in UNTRACKED_FIELDS."""
        return models.QuerySet.update(self, **kwargs)


JobManager = models.Manager.from_queryset(JobQuerySet)


class Job(models.Model):
    # CHECKLIST - when adding a new field or property to Job, check these locations:
    #   1. JOB_DIRECT_FIELDS below (if it's a model field)
    #   2. JobSerializer.Meta.fields in apps/job/serializers/job_serializer.py
    #   3. ClientJobHeaderSerializer in apps/client/serializers.py
    #   4. get_client_jobs() response dict in apps/client/services/client_rest_service.py
    #   5. KanbanService.serialize_job_for_api() in apps/job/services/kanban_service.py
    #   6. KanbanJobSerializer and KanbanColumnJobSerializer in apps/job/serializers/kanban_serializer.py
    #   7. data_quality_report.py in apps/job/services/
    #   8. JobAgingService job_info dict in apps/accounting/services.py
    #   9. serialize_job_list() in apps/workflow/api/reports/job_movement.py
    #  10. get_jobs_for_dropdown() in apps/job/utils.py
    #  11. jobs_data dict in apps/purchasing/views/purchasing_rest_views.py
    #  12. job_metrics dict in JobRestService.get_weekly_metrics() in apps/job/services/job_rest_service.py
    #  13. job_data dict in DailyTimesheetService._get_job_breakdown() in apps/timesheet/services/daily_timesheet_service.py
    #
    # Field change events are created automatically by Job.save().
    # All fields are tracked unless listed in UNTRACKED_FIELDS.
    # Business-action events (Xero, delivery docket, JSA, etc.) are
    # created by their respective services.
    #
    # Direct scalar model fields (not related objects, not properties).
    # These are enumerated here to make it easier to avoid code duplication.
    JOB_DIRECT_FIELDS = [
        "job_number",
        "name",
        "description",
        "status",
        "order_number",
        "delivery_date",
        "notes",
        "pricing_methodology",
        "price_cap",
        "speed_quality_tradeoff",
        "fully_invoiced",
        "quote_acceptance_date",
        "paid",
        "rejected_flag",
        "rdti_type",
        "min_people",
        "max_people",
    ]

    # Fields where changes are NOT audited via JobEvent. Every field NOT in
    # this set is automatically tracked — adding a new business field to Job
    # gives you audit coverage for free.
    UNTRACKED_FIELDS = frozenset(
        {
            # Auto-managed timestamps
            "id",
            "created_at",
            "updated_at",
            # Set once at creation
            "job_number",
            "created_by_id",
            # Internal cost set pointers
            "latest_estimate_id",
            "latest_quote_id",
            "latest_actual_id",
            # Derived / bookkeeping
            "fully_invoiced",
            "job_is_valid",
            # Xero sync metadata
            "xero_project_id",
            "xero_default_task_id",
            "xero_last_modified",
            "xero_last_synced",
            # Derived from status change side-effect, not an independent change
            "completed_at",
        }
    )

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, null=False, blank=False)
    JOB_STATUS_CHOICES: List[tuple[str, str]] = [
        # Main kanban columns (visible)
        ("draft", "Draft"),
        ("awaiting_approval", "Awaiting Approval"),
        ("approved", "Approved"),
        ("in_progress", "In Progress"),
        ("unusual", "Unusual"),
        ("recently_completed", "Recently Completed"),
        # Hidden statuses (maintained but not shown on kanban)
        ("special", "Special"),
        ("archived", "Archived"),
    ]

    STATUS_TOOLTIPS: Dict[str, str] = {
        # Main kanban statuses
        "draft": "Initial job creation - quote being prepared",
        "awaiting_approval": "Quote submitted and waiting for customer approval",
        "approved": "Quote approved and ready to start work",
        "in_progress": "Work has started on this job",
        "unusual": "Jobs requiring special attention - on hold, waiting for materials/staff/site",
        "recently_completed": "Work has just finished on this job (including rejected jobs)",
        # Hidden statuses
        "special": "Shop jobs, upcoming shutdowns, etc. (not visible on kanban without advanced search)",
        "archived": "The job has been paid for and picked up",
    }

    client = models.ForeignKey(
        "client.Client",
        on_delete=models.PROTECT,  # Prevent deletion of clients with jobs
        null=True,
        related_name="jobs",  # Allows reverse lookup of jobs for a client
    )
    order_number = models.CharField(max_length=100, null=True, blank=True)

    # New relationship to ClientContact
    contact = models.ForeignKey(
        "client.ClientContact",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="jobs",
        help_text="The contact person for this job",
    )
    job_number = models.IntegerField(unique=True)  # Job 1234
    description = models.TextField(
        blank=True,
        null=True,
        help_text="This becomes the first line item on the invoice",
    )

    quote_acceptance_date: Optional[datetime] = models.DateTimeField(
        null=True,
        blank=True,
    )
    delivery_date = models.DateField(null=True, blank=True)
    completed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Set automatically when job moves to recently_completed or archived",
    )
    status: str = models.CharField(
        max_length=30, choices=JOB_STATUS_CHOICES, default="draft"
    )  # type: ignore

    # Flag to track jobs that were rejected
    rejected_flag: bool = models.BooleanField(
        default=False,
        help_text="Indicates if this job was rejected (shown in Archived with rejected styling)",
    )

    rdti_type = models.CharField(
        max_length=20,
        choices=RDTIType.choices,
        null=True,
        blank=True,
        help_text="R&D Tax Incentive classification for this job",
    )

    PRICING_METHODOLOGY_CHOICES = [
        ("time_materials", "Time & Materials"),
        ("fixed_price", "Fixed Price"),
    ]

    pricing_methodology = models.CharField(
        max_length=20,
        choices=PRICING_METHODOLOGY_CHOICES,
        default="time_materials",
        help_text=(
            "Determines whether job uses quotes or time and materials pricing type."
        ),
    )

    price_cap = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=(
            "Maximum amount to invoice for T&M jobs (do not exceed). "
            "For quoted jobs it is set to the quote."
        ),
    )

    speed_quality_tradeoff = models.CharField(
        max_length=20,
        choices=SpeedQualityTradeoff.choices,
        default=SpeedQualityTradeoff.NORMAL,
        help_text="Speed vs quality tradeoff for workshop execution",
    )

    # Decided not to bother with parent for now since we don't have a hierarchy of jobs.
    # Can be restored.
    # Parent would provide an alternative to historical records for tracking changes.
    # parent: models.ForeignKey = models.ForeignKey(
    #     "self",
    #     null=True,
    #     blank=True,
    #     related_name="revisions",
    #     on_delete=models.SET_NULL,
    # )
    # Shop job has no client (client_id is None)

    job_is_valid = models.BooleanField(default=False)
    collected: bool = models.BooleanField(default=False)
    paid: bool = models.BooleanField(default=False)
    fully_invoiced: bool = models.BooleanField(
        default=False,
        help_text="The total value of invoices for this job matches the total value of the job.",
    )
    charge_out_rate = (
        models.DecimalField(  # TODO: This needs to be added to the edit job form
            max_digits=10,
            decimal_places=2,
            null=False,  # Not nullable because save() ensures a value
            blank=False,  # Should be required in forms too
        )
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    history: HistoricalRecords = HistoricalRecords()

    objects = JobManager()

    complex_job = models.BooleanField(default=False)

    notes = models.TextField(
        blank=True,
        null=True,
        help_text="Internal notes about the job. Not shown on the invoice.",
    )

    created_by = models.ForeignKey(Staff, on_delete=models.PROTECT, null=True)

    people = models.ManyToManyField(Staff, related_name="assigned_jobs")

    # Latest cost set snapshots for linking to current estimates/quotes/actuals
    latest_estimate = models.OneToOneField(
        "CostSet",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="Latest estimate cost set snapshot",
    )

    latest_quote = models.OneToOneField(
        "CostSet",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="Latest quote cost set snapshot",
    )

    latest_actual = models.OneToOneField(
        "CostSet",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="Latest actual cost set snapshot",
    )

    PRIORITY_INCREMENT = 200

    priority = models.FloatField(
        default=0.0,
        help_text="Priority of the job, higher numbers are higher priority.",
    )

    min_people = models.IntegerField(
        default=1,
        help_text="Minimum number of workshop staff required to work on this job simultaneously",
    )
    max_people = models.IntegerField(
        default=1,
        help_text="Maximum number of workshop staff that can work on this job simultaneously",
    )

    # Xero Projects sync fields
    xero_project_id = models.CharField(
        max_length=255, unique=True, null=True, blank=True
    )
    xero_default_task_id = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text="Xero task ID for the default Labor task used for time entries",
        # TODO: This won't work long term - need proper task management system
    )
    xero_last_modified = models.DateTimeField(null=True, blank=True)
    xero_last_synced = models.DateTimeField(null=True, blank=True, default=timezone.now)

    # Default pay item for time entry - prepopulates the pay item dropdown.
    # Work jobs default to Ordinary Time, leave jobs to their specific type.
    default_xero_pay_item = models.ForeignKey(
        "workflow.XeroPayItem",
        on_delete=models.PROTECT,
        related_name="jobs",
        help_text="Default pay item for time entry. Prepopulates dropdown, can be overridden.",
    )

    class Meta:
        verbose_name = "Job"
        verbose_name_plural = "Jobs"
        ordering = ["-priority", "-created_at"]
        indexes = [
            Index(fields=["status", "priority"], name="job_priority_status_idx"),
        ]

    @classmethod
    def _calculate_next_priority_for_status(cls, status_value: str) -> float:
        max_entry = (
            cls.objects.filter(status=status_value).aggregate(Max("priority"))[
                "priority__max"
            ]
            or 0.0
        )
        return max_entry + cls.PRIORITY_INCREMENT

    @property
    def shop_job(self) -> bool:
        """Indicates if this is a shop job (belongs to shop client)."""
        if not self.client_id:
            return False
        from apps.client.models import Client

        try:
            shop_client_id = Client.get_shop_client_id()
            return str(self.client_id) == shop_client_id
        except (ValueError, RuntimeError):
            # shop_client_name not configured - can't determine
            return False

    @shop_job.setter
    def shop_job(self, value: bool) -> None:
        """Sets whether this is a shop job by updating the client ID."""
        from apps.client.models import Client

        if value:
            shop_client_id = Client.get_shop_client_id()
            self.client_id = uuid.UUID(shop_client_id)
        else:
            self.client_id = None

    @property
    def quoted(self) -> bool:
        # If the attribute doesn't exists (default behaviour in Django relationships)
        # then the exception will be raised, in which case this only means we don't have a quote currently
        try:
            return self.quote is not None
        except AttributeError:
            return False

    def __str__(self) -> str:
        status_display = self.get_status_display()
        return f"[Job {self.job_number}] {self.name} ({status_display})"

    def clean(self) -> None:
        from django.core.exceptions import ValidationError

        errors = {}
        if self.min_people < 1:
            errors["min_people"] = "min_people must be at least 1"
        if self.max_people < 1:
            errors["max_people"] = "max_people must be at least 1"
        if self.max_people < self.min_people:
            errors["max_people"] = "max_people must be >= min_people"
        if errors:
            raise ValidationError(errors)

    def get_absolute_url(self) -> str:
        """Front-end URL for this job."""
        from django.conf import settings

        if not getattr(settings, "FRONT_END_URL", ""):
            raise ValueError("FRONT_END_URL is not configured")
        return f"{settings.FRONT_END_URL.rstrip('/')}/jobs/{self.id}"

    def get_latest(self, kind: str) -> Optional["CostSet"]:
        """
        Returns the respective CostSet or None.

        Args:
            kind: 'estimate', 'quote' or 'actual'

        Returns:
            CostSet instance or None
        """
        field_mapping = {
            "estimate": "latest_estimate",
            "quote": "latest_quote",
            "actual": "latest_actual",
        }

        if kind not in field_mapping:
            raise ValueError(
                f"Invalid kind '{kind}'. Must be one of: {list(field_mapping.keys())}"
            )

        return getattr(self, field_mapping[kind], None)

    def set_latest(self, kind: str, cost_set: "CostSet", staff) -> None:
        """
        Updates pointer and saves.

        Args:
            kind: 'estimate', 'quote' or 'actual'
            cost_set: CostSet instance to set as latest
            staff: Staff to attribute the save event to
        """
        field_mapping = {
            "estimate": "latest_estimate",
            "quote": "latest_quote",
            "actual": "latest_actual",
        }

        if kind not in field_mapping:
            raise ValueError(
                f"Invalid kind '{kind}'. Must be one of: {list(field_mapping.keys())}"
            )

        # Validate that the cost_set belongs to this job and is of the correct kind
        if cost_set.job != self:
            raise ValueError("CostSet must belong to this job")

        if cost_set.kind != kind:
            raise ValueError(
                f"CostSet kind '{cost_set.kind}' does not match requested kind '{kind}'"
            )

        setattr(self, field_mapping[kind], cost_set)
        self.save(staff=staff, update_fields=[field_mapping[kind], "updated_at"])

    @property
    def job_display_name(self) -> str:
        """
        Returns a formatted display name for the job including client name.
        Format: job_number - (first 12 chars of client name), job_name
        """
        client_name = self.client.name[:12] if self.client else "No Client"
        return f"{self.job_number} - {client_name}, {self.name}"

    @property
    def start_date(self) -> Optional[date]:
        """Returns the earliest accounting_date from actual CostLines."""
        return self.latest_actual.cost_lines.aggregate(earliest=Min("accounting_date"))[
            "earliest"
        ]

    @property
    def last_financial_activity_date(self) -> Optional[date]:
        """Returns the latest accounting_date from actual CostLines."""
        return self.latest_actual.cost_lines.aggregate(latest=Max("accounting_date"))[
            "latest"
        ]

    def generate_job_number(self) -> int:
        company_defaults: CompanyDefaults = CompanyDefaults.get_solo()
        starting_number: int = company_defaults.starting_job_number
        highest_job: int = (
            Job.objects.all().aggregate(Max("job_number"))["job_number__max"] or 0
        )
        next_job_number = max(starting_number, highest_job + 1)
        return next_job_number

    def save(self, *args, **kwargs):
        staff = kwargs.pop("staff", None)

        if staff is None:
            raise ValueError(
                "Job.save() requires staff; use Staff.get_automation_user() "
                "for system-initiated writes"
            )

        # Event enrichment context — passed through to _create_change_events()
        enrichment_keys = (
            "change_id",
            "delta_meta",
            "schema_version",
            "delta_checksum",
            "event_type_override",
            "priority_position",
        )
        enrichment = {k: kwargs.pop(k) for k in enrichment_keys if k in kwargs}

        update_fields = kwargs.get("update_fields")

        is_new = self._state.adding
        original_job = None

        # Track original values for change detection
        if not is_new:
            original_job = Job.objects.get(pk=self.pk)

        if is_new or not self.created_by:
            self.created_by = staff

        if self.charge_out_rate is None:
            company_defaults = CompanyDefaults.get_solo()
            self.charge_out_rate = company_defaults.charge_out_rate

        # Default to "Ordinary Time" pay item if not specified
        if self.default_xero_pay_item_id is None:
            ordinary_time = XeroPayItem.get_ordinary_time()
            if not ordinary_time:
                raise ValueError(
                    "Cannot create Job: 'Ordinary Time' XeroPayItem not found. "
                    "Run Xero sync or check database seed data."
                )
            self.default_xero_pay_item = ordinary_time

        if is_new:
            # Ensure job_number is generated for new instances before saving
            self.job_number = self.generate_job_number()
            if not self.job_number:
                logger.error("Failed to generate a job number. Cannot save job.")
                raise ValueError("Job number generation failed.")
            logger.debug(f"Saving new job with job number: {self.job_number}")

            # To assure all jobs have a priority
            with transaction.atomic():
                default_priority = self._calculate_next_priority_for_status(self.status)
                self.priority = default_priority

                # Save the job first
                super(Job, self).save(*args, **kwargs)

                # Create initial CostSet instances (modern system)
                logger.debug("Creating initial CostSet entries.")

                # Initialize summary for new cost sets to avoid serialization errors
                initial_summary = {"cost": 0.0, "rev": 0.0, "hours": 0.0}

                # Create estimate cost set
                estimate_cost_set = CostSet.objects.create(
                    job=self, kind="estimate", rev=1, summary=initial_summary
                )
                self.latest_estimate = estimate_cost_set

                # Create quote cost set
                quote_cost_set = CostSet.objects.create(
                    job=self, kind="quote", rev=1, summary=initial_summary
                )
                self.latest_quote = quote_cost_set

                # Create actual cost set
                actual_cost_set = CostSet.objects.create(
                    job=self, kind="actual", rev=1, summary=initial_summary
                )
                self.latest_actual = actual_cost_set

                logger.debug("Initial CostSets created successfully.")

                # Save the references back to the DB
                super(Job, self).save(
                    update_fields=[
                        "latest_estimate",
                        "latest_quote",
                        "latest_actual",
                    ]
                )

                # Note: Job creation event is now handled in JobRestService.create_job()
                # to prevent duplicate event creation between model and service layers

        else:
            # Order matters:
            #   1. Detect diff against the original row.
            #   2. Apply side effects (may mutate self, e.g. completed_at).
            #   3. Extend update_fields so side-effect mutations reach the DB.
            #   4. Persist, then write the event atomically against the row.
            (
                changes_before,
                changes_after,
                detail_changes,
                event_types,
            ) = self._detect_field_changes(original_job, update_fields=update_fields)

            if changes_before:
                side_effect_fields = self._apply_change_side_effects(
                    changes_before, changes_after
                )
                if side_effect_fields and kwargs.get("update_fields") is not None:
                    kwargs["update_fields"] = list(
                        set(kwargs["update_fields"]) | side_effect_fields
                    )

            with transaction.atomic():
                super(Job, self).save(*args, **kwargs)
                if changes_before:
                    self._record_change_event(
                        changes_before,
                        changes_after,
                        detail_changes,
                        event_types,
                        staff,
                        enrichment,
                    )

    # ── Field change tracking ──────────────────────────────────────────
    #
    # All concrete fields are tracked unless listed in UNTRACKED_FIELDS.
    # Fields with custom description logic have handlers in _FIELD_HANDLERS.
    # Any tracked field without a handler gets a generic "X changed" event.

    def _detect_field_changes(self, original_job, update_fields=None):
        """Return (changes_before, changes_after, detail_changes, event_types).

        When update_fields is passed to save(), only those fields are considered —
        in-memory mutations on other fields weren't persisted, so emitting events
        for them would misrepresent what changed on the row.
        """
        changes_before = {}
        changes_after = {}
        detail_changes = []
        event_types = []

        restricted = set(update_fields) if update_fields is not None else None

        for field in self._meta.get_fields():
            # Only concrete scalar fields (skip reverse FKs, M2M, generic relations)
            if not hasattr(field, "attname") or field.many_to_many:
                continue
            attr = field.attname
            if attr in self.UNTRACKED_FIELDS:
                continue
            if restricted is not None and not (
                attr in restricted or field.name in restricted
            ):
                continue

            old_val = getattr(original_job, attr)
            new_val = getattr(self, attr)

            if old_val == new_val:
                continue

            changes_before[attr] = _json_safe(old_val)
            changes_after[attr] = _json_safe(new_val)

            # Use custom handler if one exists, otherwise generic detail
            handler = self._FIELD_HANDLERS.get(attr)
            if handler:
                result = handler(self, old_val, new_val)
                if result:
                    event_types.append(result[0])
                    detail_changes.append(result[1])
            else:
                # Generic detail using field verbose_name
                label = field.verbose_name
                detail_changes.append(
                    {
                        "field_name": label,
                        "old_value": str(_json_safe(old_val)),
                        "new_value": str(_json_safe(new_val)),
                    }
                )
                event_types.append("job_updated")

        return changes_before, changes_after, detail_changes, event_types

    def _record_change_event(
        self,
        changes_before,
        changes_after,
        detail_changes,
        event_types,
        staff,
        enrichment,
    ):
        """Create the single JobEvent for a batch of detected field changes."""
        event_type = enrichment.pop("event_type_override", None)
        if not event_type:
            event_type = self._infer_event_type(event_types, changes_after)

        detail = {"changes": detail_changes}
        priority_position = enrichment.get("priority_position")
        if event_type == "priority_changed" and priority_position:
            # Float changed but rank didn't — drag was a no-op visually.
            # Skip the JobEvent so we don't pollute the audit log. Log a
            # warning so we can spot it if it starts happening unexpectedly
            # (e.g. a UI bug that fires reorder requests on every click).
            if priority_position.get("old_position") == priority_position.get(
                "new_position"
            ):
                logger.warning(
                    "Suppressed no-op priority_changed event for job %s "
                    "(rank unchanged at %s of %s in %s)",
                    self.pk,
                    priority_position.get("new_position"),
                    priority_position.get("new_total"),
                    priority_position.get("new_status"),
                )
                return
            detail["position"] = priority_position

        JobEvent.objects.create(
            job=self,
            event_type=event_type,
            detail=detail,
            staff=staff,
            delta_before=changes_before,
            delta_after=changes_after,
            schema_version=enrichment.get("schema_version", 0),
            change_id=enrichment.get("change_id"),
            delta_meta=enrichment.get("delta_meta"),
            delta_checksum=enrichment.get("delta_checksum", ""),
        )

    def _apply_change_side_effects(self, changes_before, changes_after):
        """Mutate self for non-event side effects and return the fields touched.

        Returned set is used to extend `update_fields` so the mutations reach
        the DB when the caller restricted which fields to save.
        """
        mutated = set()
        if "status" in changes_after:
            new_status = changes_after["status"]
            # Set completed_at on first transition to a completed status
            if (
                new_status in ("recently_completed", "archived")
                and not self.completed_at
            ):
                self.completed_at = timezone.now()
                mutated.add("completed_at")
            # Clear completed_at if moved back to a non-completed status
            elif new_status not in ("recently_completed", "archived") and (
                self.completed_at is not None
            ):
                self.completed_at = None
                mutated.add("completed_at")
        return mutated

    @staticmethod
    def _infer_event_type(event_types, changes_after):
        """Pick the most significant event type from collected types."""
        # Rejected flag + archived status → job_rejected
        if (
            changes_after.get("rejected_flag") is True
            and changes_after.get("status") == "archived"
        ):
            return "job_rejected"
        # Status change is the most significant single-field type
        if "status_changed" in event_types:
            return "status_changed"
        # Single field change → use that field's specific type
        if len(event_types) == 1:
            return event_types[0]
        # Multiple field changes → generic
        return "job_updated"

    # ── Field handlers ─────────────────────────────────────────────────
    #
    # Each handler takes (self, old_value, new_value) and returns
    # (event_type, detail_dict) or None to skip that field.
    # detail_dict has keys: field_name, old_value, new_value (all strings).
    # Handlers MUST NOT create events directly.

    @staticmethod
    def _handle_status_change(self_job, old_status, new_status):
        old_display = dict(Job.JOB_STATUS_CHOICES).get(old_status, old_status)
        new_display = dict(Job.JOB_STATUS_CHOICES).get(new_status, new_status)
        return (
            "status_changed",
            {
                "field_name": "Status",
                "old_value": str(old_display),
                "new_value": str(new_display),
            },
        )

    @staticmethod
    def _handle_client_change(self_job, old_client_id, new_client_id):
        old_client = "Shop Job"
        new_client = "Shop Job"
        if old_client_id:
            try:
                old_client = Client.objects.get(id=old_client_id).name
            except Exception:
                old_client = "Unknown Client"
        if new_client_id:
            new_client = self_job.client.name if self_job.client else "Unknown Client"
        return (
            "client_changed",
            {"field_name": "Client", "old_value": old_client, "new_value": new_client},
        )

    @staticmethod
    def _handle_contact_change(self_job, old_contact_id, new_contact_id):
        old_contact = "None"
        new_contact = "None"
        if old_contact_id:
            try:
                from apps.client.models import ClientContact

                old_contact = ClientContact.objects.get(id=old_contact_id).name
            except Exception:
                old_contact = "Unknown Contact"
        if new_contact_id:
            new_contact = (
                self_job.contact.name if self_job.contact else "Unknown Contact"
            )
        return (
            "contact_changed",
            {
                "field_name": "Primary contact",
                "old_value": old_contact,
                "new_value": new_contact,
            },
        )

    @staticmethod
    def _handle_xero_pay_item_change(self_job, old_pay_item_id, new_pay_item_id):
        old_name = "None"
        new_name = "None"
        if old_pay_item_id:
            try:
                old_name = XeroPayItem.objects.get(id=old_pay_item_id).name
            except Exception:
                old_name = "Unknown"
        if new_pay_item_id:
            new_name = (
                self_job.default_xero_pay_item.name
                if self_job.default_xero_pay_item
                else "Unknown"
            )
        return (
            "job_updated",
            {
                "field_name": "Xero pay item",
                "old_value": old_name,
                "new_value": new_name,
            },
        )

    @staticmethod
    def _handle_text_field_change(event_type, field_display_name):
        """Factory: returns a handler for text field changes."""

        def handler(_self_job, old_value, new_value):
            if old_value or new_value:
                return (
                    event_type,
                    {
                        "field_name": field_display_name,
                        "old_value": old_value or "",
                        "new_value": new_value or "",
                    },
                )
            return None

        return handler

    @staticmethod
    def _handle_date_change(event_type, field_display_name):
        """Factory: returns a handler for date field changes."""

        def handler(_self_job, old_date, new_date):
            old_str = old_date.strftime("%Y-%m-%d") if old_date else "None"
            new_str = new_date.strftime("%Y-%m-%d") if new_date else "None"
            return (
                event_type,
                {
                    "field_name": field_display_name,
                    "old_value": old_str,
                    "new_value": new_str,
                },
            )

        return handler

    @staticmethod
    def _handle_quote_acceptance_change(_self_job, old_date, new_date):
        if not old_date and new_date:
            return (
                "quote_accepted",
                {
                    "field_name": "Quote acceptance date",
                    "old_value": "None",
                    "new_value": new_date.strftime("%Y-%m-%d at %H:%M"),
                },
            )
        elif old_date and not new_date:
            return (
                "job_updated",
                {
                    "field_name": "Quote acceptance date",
                    "old_value": old_date.strftime("%Y-%m-%d"),
                    "new_value": "None",
                },
            )
        return None

    @staticmethod
    def _handle_pricing_methodology_change(_self_job, old_method, new_method):
        old_display = dict(Job.PRICING_METHODOLOGY_CHOICES).get(old_method, old_method)
        new_display = dict(Job.PRICING_METHODOLOGY_CHOICES).get(new_method, new_method)
        return (
            "pricing_changed",
            {
                "field_name": "Pricing methodology",
                "old_value": str(old_display),
                "new_value": str(new_display),
            },
        )

    @staticmethod
    def _handle_speed_quality_tradeoff_change(_self_job, old_tradeoff, new_tradeoff):
        old_display = dict(SpeedQualityTradeoff.choices).get(old_tradeoff, old_tradeoff)
        new_display = dict(SpeedQualityTradeoff.choices).get(new_tradeoff, new_tradeoff)
        return (
            "job_updated",
            {
                "field_name": "Speed/quality tradeoff",
                "old_value": str(old_display),
                "new_value": str(new_display),
            },
        )

    @staticmethod
    def _handle_rdti_type_change(_self_job, old_type, new_type):
        old_display = dict(RDTIType.choices).get(old_type, old_type or "None")
        new_display = dict(RDTIType.choices).get(new_type, new_type or "None")
        return (
            "job_updated",
            {
                "field_name": "RDTI classification",
                "old_value": str(old_display),
                "new_value": str(new_display),
            },
        )

    @staticmethod
    def _handle_boolean_change(true_event, false_event, field_name):
        """Factory: returns a handler for boolean field changes."""

        def handler(_self_job, old_value, new_value):
            if new_value and not old_value:
                return (
                    true_event,
                    {"field_name": field_name, "old_value": "No", "new_value": "Yes"},
                )
            elif old_value and not new_value:
                return (
                    false_event,
                    {"field_name": field_name, "old_value": "Yes", "new_value": "No"},
                )
            return None

        return handler

    # Maps field attname → handler(self_job, old, new) → (event_type, detail_dict) | None
    # Fields not listed here get a generic detail via verbose_name.
    _FIELD_HANDLERS = {
        "status": _handle_status_change.__func__,
        "name": lambda _self, old, new: (
            "job_updated",
            {"field_name": "Job name", "old_value": str(old), "new_value": str(new)},
        ),
        "client_id": _handle_client_change.__func__,
        "contact_id": _handle_contact_change.__func__,
        "order_number": lambda _self, old, new: (
            "job_updated",
            {
                "field_name": "Order number",
                "old_value": str(old or "None"),
                "new_value": str(new or "None"),
            },
        ),
        "description": _handle_text_field_change.__func__(
            "job_updated", "Job description"
        ),
        "notes": _handle_text_field_change.__func__("notes_updated", "Internal notes"),
        "delivery_date": _handle_date_change.__func__(
            "delivery_date_changed", "Delivery date"
        ),
        "quote_acceptance_date": _handle_quote_acceptance_change.__func__,
        "pricing_methodology": _handle_pricing_methodology_change.__func__,
        "speed_quality_tradeoff": _handle_speed_quality_tradeoff_change.__func__,
        "charge_out_rate": lambda _self, old, new: (
            "pricing_changed",
            {
                "field_name": "Charge out rate",
                "old_value": f"${old}/hour",
                "new_value": f"${new}/hour",
            },
        ),
        "price_cap": lambda _self, old, new: (
            "pricing_changed",
            {
                "field_name": "Price cap",
                "old_value": f"${old or 'None'}",
                "new_value": f"${new or 'None'}",
            },
        ),
        "priority": lambda _self, old, new: (
            "priority_changed",
            {
                "field_name": "Job priority",
                "old_value": str(old),
                "new_value": str(new),
            },
        ),
        "paid": _handle_boolean_change.__func__(
            "payment_received",
            "payment_updated",
            "Paid",
        ),
        "collected": _handle_boolean_change.__func__(
            "job_collected",
            "collection_updated",
            "Collected",
        ),
        "complex_job": _handle_boolean_change.__func__(
            "job_updated",
            "job_updated",
            "Complex job",
        ),
        "rdti_type": _handle_rdti_type_change.__func__,
        "default_xero_pay_item_id": _handle_xero_pay_item_change.__func__,
    }
