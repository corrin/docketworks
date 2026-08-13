"""The Job model: the core domain aggregate with automatic JobEvent audit tracking."""

import logging
import uuid
from collections.abc import Callable, Iterable
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, ClassVar

from django.core.exceptions import ObjectDoesNotExist
from django.db import models, transaction
from django.db.models import Index, Max, Min
from django.utils import timezone

from apps.core.data_events import notify_data_changed

# v1 home: apps.workflow.models — CompanyDefaults lives in apps.core in v2.
from apps.core.models import CompanyDefaults
from apps.job.enums import RDTIType, SpeedQualityTradeoff

from .costing import CostSet
from .job_event import JobEvent
from .labour import JobLabourRate, LabourSubtype

if TYPE_CHECKING:
    from apps.accounts.models import Staff

logger = logging.getLogger(__name__)

# What _json_safe produces: the JSON-serializable form of a model field value.
_JsonScalar = str | int | float | bool | None


def _json_safe(value: object) -> _JsonScalar:
    """Convert a model field value to a JSON-serializable form."""
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (str, int, float, bool)):
        # v1 wrote `hasattr(value, "__str__") and not isinstance(...)`;
        # every object has __str__, so passthrough types are exactly these.
        return value
    return str(value)


class JobQuerySet(models.QuerySet["Job"]):
    """Custom QuerySet that prevents .update() on tracked fields.

    All Job field changes must go through Job.save(staff=...) so that
    JobEvents are created automatically. Attempting to .update() a tracked
    field raises RuntimeError at dev time. For migrations or bookkeeping
    fields, use .untracked_update().
    """

    def create(self, **kwargs: Any) -> "Job":
        """Create a Job, routing through save(staff=...) like every other path.

        Job.save() requires staff, so Manager.create()'s default implementation
        (which calls save() with no kwargs) would always raise. This override
        pops the staff kwarg and threads it through.
        """
        if "staff" not in kwargs:
            raise TypeError(
                "Job.objects.create() requires staff=... (routes through Job.save(staff=...))"
            )
        staff = kwargs.pop("staff")
        obj = self.model(**kwargs)
        self._for_write = True
        obj.save(staff=staff, using=self.db)
        return obj

    def update(self, **kwargs: Any) -> int:
        """Reject .update() on tracked fields; route those through save(staff=...)."""
        tracked = set(kwargs.keys()) - Job.UNTRACKED_FIELDS
        if tracked:
            raise RuntimeError(
                f"Cannot .update() tracked fields {tracked}. "
                f"Use save(staff=...) so JobEvents are created. "
                f"For migrations or bookkeeping, use .untracked_update()."
            )
        return self.untracked_update(**kwargs)

    def untracked_update(self, **kwargs: Any) -> int:
        """Bypass the tracked-field guard.

        Use only for migrations and bookkeeping fields that are in
        UNTRACKED_FIELDS.

        Every Job UPDATE arrives here — ``update()`` delegates after its guard
        and ``touch_updated_at()`` is a named case of it — which is what makes
        this the one place able to announce a write no ``post_save`` fires for.
        The announcement lives on the class rather than at each bookkeeping
        call site because the call sites are what get forgotten: two of them
        (``purchase_order_service`` on line receipt, ``job_service``'s
        invoice-flag reset) moved the kanban freshness timestamp for the poll
        and pushed nothing. Announcing on writes that move no version is free
        — the publisher coalesces and its payload is idempotent — while
        missing one is a permanently stale tab.
        """
        changed = models.QuerySet.update(self, **kwargs)
        if changed == 0:
            return 0
        # Through the core observer seam: apps.job must not import
        # apps.operations (layer contract).
        notify_data_changed()
        return changed

    def touch_updated_at(self, *, at: datetime) -> int:
        """Advance only the aggregate freshness timestamp."""
        return self.untracked_update(updated_at=at)


JobManager = models.Manager.from_queryset(JobQuerySet)


def _handle_boolean_change(
    true_event: str, false_event: str, field_name: str
) -> Callable[..., tuple[str, dict[str, str]] | None]:
    """Return a handler for boolean field changes (factory)."""

    def handler(
        _self_job: Any, old_value: Any, new_value: Any
    ) -> tuple[str, dict[str, str]] | None:
        if new_value and not old_value:
            return (
                true_event,
                {"field_name": field_name, "old_value": "No", "new_value": "Yes"},
            )
        if old_value and not new_value:
            return (
                false_event,
                {"field_name": field_name, "old_value": "Yes", "new_value": "No"},
            )
        return None

    return handler


class Job(models.Model):
    """A customer (or shop) job: the aggregate root of the costing domain."""

    # CHECKLIST - when adding a new field or property to Job, check these locations:
    #   1. JOB_DIRECT_FIELDS below (if it's a model field)
    #   2. JobSerializer.Meta.fields in apps/job/serializers/job_serializer.py
    #   3. ClientJobHeaderSerializer in apps/company/serializers.py
    #   4. get_company_jobs() response dict in apps/company/services/company_rest_service.py
    #   5. KanbanService.serialize_job_for_api() in apps/job/services/kanban_service.py
    #   6. KanbanJobSerializer and KanbanColumnJobSerializer
    #      in apps/job/serializers/kanban_serializer.py
    #   7. TestSerializeJobForApi.test_serialized_shape_for_fully_populated_job
    #      in apps/job/tests/test_kanban_service.py
    #   8. data_quality_report.py in apps/job/services/
    #   9. JobAgingService job_info dict in apps/accounting/services/core.py
    #  10. serialize_job_list() in apps/workflow/api/reports/job_movement.py
    #  11. get_jobs_for_dropdown() in apps/job/utils.py
    #  12. jobs_data dict in apps/purchasing/views/purchasing_rest_views.py
    #  13. job_metrics dict in JobRestService.get_weekly_metrics()
    #      in apps/job/services/job_rest_service.py
    #  14. job_data dict in DailyTimesheetService._get_job_breakdown()
    #      in apps/timesheet/services/daily_timesheet_service.py
    #
    # Field change events are created automatically by Job.save().
    # All fields are tracked unless listed in UNTRACKED_FIELDS.
    # Business-action events (Xero, delivery docket, JSA, etc.) are
    # created by their respective services.
    #
    # Direct scalar model fields (not related objects, not properties).
    # These are enumerated here to make it easier to avoid code duplication.
    JOB_DIRECT_FIELDS: ClassVar[list[str]] = [
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
        "is_urgent",
    ]

    # The front-desk completion checklist, in display order. The Finish Job
    # serializers derive their field lists from this, so an item is declared
    # once.
    COMPLETION_CHECKLIST_FIELDS: ClassVar[list[str]] = [
        "foreman_signed_off",
        "timesheets_collected",
        "materials_checked",
        "customer_called",
        "released",
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
    JOB_STATUS_CHOICES: ClassVar[list[tuple[str, str]]] = [
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

    STATUS_TOOLTIPS: ClassVar[dict[str, str]] = {
        # Main kanban statuses
        "draft": "Initial job creation - quote being prepared",
        "awaiting_approval": "Quote submitted and waiting for customer approval",
        "approved": "Quote approved and ready to start work",
        "in_progress": "Work has started on this job",
        "unusual": "Jobs requiring special attention - on hold, waiting for materials/staff/site",
        "recently_completed": "Work has just finished on this job (including rejected jobs)",
        # Hidden statuses
        "special": (
            "Shop jobs, upcoming shutdowns, etc. (not visible on kanban without advanced search)"
        ),
        "archived": "The job has been paid for and picked up",
    }

    company = models.ForeignKey(
        "company.Company",
        on_delete=models.PROTECT,  # Prevent deletion of companies with jobs
        null=True,
        # blank=True to match null=True: a company-less job is a state v1 has
        # produced for 14 months and the schema has always permitted. Without
        # it the model declares a stricter contract than the column, and
        # full_clean() rejects rows the database was designed to accept.
        blank=True,
        related_name="jobs",  # Allows reverse lookup of jobs for a company
    )
    order_number = models.CharField(max_length=100, null=True, blank=True)  # noqa: DJ001 -- restored column retains nullable storage

    person = models.ForeignKey(
        "company.Person",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="jobs",
        help_text="The person for this job",
    )
    job_number = models.IntegerField(unique=True)  # Job 1234
    description = models.TextField(  # noqa: DJ001 -- restored column retains nullable storage
        blank=True,
        null=True,
        help_text="This becomes the first line item on the invoice",
    )

    quote_acceptance_date = models.DateTimeField(
        null=True,
        blank=True,
    )
    delivery_date = models.DateField(null=True, blank=True)
    completed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Set automatically when job moves to recently_completed or archived",
    )
    status = models.CharField(max_length=30, choices=JOB_STATUS_CHOICES, default="draft")

    # Flag to track jobs that were rejected
    rejected_flag = models.BooleanField(
        default=False,
        help_text="Indicates if this job was rejected (shown in Archived with rejected styling)",
    )

    rdti_type = models.CharField(  # noqa: DJ001 -- restored column retains nullable storage
        max_length=20,
        choices=RDTIType.choices,
        null=True,
        blank=True,
        help_text="R&D Tax Incentive classification for this job",
    )

    PRICING_METHODOLOGY_CHOICES: ClassVar[list[tuple[str, str]]] = [
        ("time_materials", "Time & Materials"),
        ("fixed_price", "Fixed Price"),
    ]

    pricing_methodology = models.CharField(
        max_length=20,
        choices=PRICING_METHODOLOGY_CHOICES,
        default="time_materials",
        help_text=("Determines whether job uses quotes or time and materials pricing type."),
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
    # Can be restored (see v1 for the commented-out self-FK).
    # Parent would provide an alternative to historical records for tracking changes.
    # Shop job has no company (company_id is None)

    job_is_valid = models.BooleanField(default=False)
    paid = models.BooleanField(default=False)

    # Front-desk completion checklist. Each is a fact only a person knows, so
    # none of them can be derived. Ticking one writes a job-history event through
    # _FIELD_HANDLERS below; nothing here blocks invoicing or moves the job.
    foreman_signed_off = models.BooleanField(default=False)
    timesheets_collected = models.BooleanField(default=False)
    materials_checked = models.BooleanField(default=False)
    customer_called = models.BooleanField(default=False)
    released = models.BooleanField(
        default=False,
        help_text="The job has left our possession, by collection, delivery or on-site install.",
    )
    fully_invoiced = models.BooleanField(
        default=False,
        help_text="The total value of invoices for this job matches the total value of the job.",
    )
    # Charge-out rates live in JobLabourRate, one row per labour subtype.

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    complex_job = models.BooleanField(default=False)

    is_urgent = models.BooleanField(
        default=False,
        help_text="Whether this job requires urgent rates and priority handling",
    )

    notes = models.TextField(  # noqa: DJ001 -- restored column retains nullable storage
        blank=True,
        null=True,
        help_text="Internal notes about the job. Not shown on the invoice.",
    )

    # blank=True for the same reason as company above: jobs predating
    # attribution legitimately have no creator.
    created_by = models.ForeignKey(
        "accounts.Staff", on_delete=models.PROTECT, null=True, blank=True
    )

    people = models.ManyToManyField("accounts.Staff", related_name="assigned_jobs")

    # Latest cost set snapshots for linking to current estimates/quotes/actuals
    latest_estimate = models.OneToOneField(
        "CostSet",
        on_delete=models.RESTRICT,
        null=False,
        blank=False,
        related_name="+",
        help_text="Latest estimate cost set snapshot",
    )

    latest_quote = models.OneToOneField(
        "CostSet",
        on_delete=models.RESTRICT,
        null=False,
        blank=False,
        related_name="+",
        help_text="Latest quote cost set snapshot",
    )

    latest_actual = models.OneToOneField(
        "CostSet",
        on_delete=models.RESTRICT,
        null=False,
        blank=False,
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
    xero_project_id = models.CharField(max_length=255, unique=True, null=True, blank=True)
    xero_default_task_id = models.CharField(  # noqa: DJ001 -- restored column retains nullable storage
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
    # v1 reference: "workflow.XeroPayItem" — the model's v2 home is the xero app.
    default_xero_pay_item = models.ForeignKey(
        "xero.XeroPayItem",
        on_delete=models.PROTECT,
        related_name="jobs",
        help_text="Default pay item for time entry. Prepopulates dropdown, can be overridden.",
    )

    objects = JobManager()

    class Meta:
        verbose_name = "Job"
        verbose_name_plural = "Jobs"
        ordering: ClassVar[list[str]] = ["-priority", "-created_at"]
        indexes: ClassVar[list[Index]] = [
            Index(fields=["status", "priority"], name="job_priority_status_idx"),
        ]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=~models.Q(description=""), name="job_job_description_not_blank"
            ),
            models.CheckConstraint(condition=~models.Q(notes=""), name="job_job_notes_not_blank"),
            models.CheckConstraint(
                condition=~models.Q(order_number=""), name="order_number_not_blank"
            ),
            models.CheckConstraint(condition=~models.Q(rdti_type=""), name="rdti_type_not_blank"),
            models.CheckConstraint(
                condition=~models.Q(xero_default_task_id=""),
                name="xero_default_task_id_not_blank",
            ),
            models.CheckConstraint(
                condition=~models.Q(xero_project_id=""), name="xero_project_id_not_blank"
            ),
        ]

    def __str__(self) -> str:
        status_display = self.get_status_display()
        return f"[Job {self.job_number}] {self.name} ({status_display})"

    def save(self, *args: Any, **kwargs: Any) -> None:  # noqa: C901, PLR0912, PLR0915
        """Save the job, generating numbers/cost sets on create and JobEvents on change."""
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
            if update_fields is not None:
                update_field_names = (
                    [update_fields] if isinstance(update_fields, str) else list(update_fields)
                )
                if update_field_names and "updated_at" not in update_field_names:
                    kwargs["update_fields"] = [*update_field_names, "updated_at"]
                    update_fields = kwargs["update_fields"]

        if is_new or not self.created_by:
            self.created_by = staff

        # Default to "Ordinary Time" pay item if not specified
        if self.default_xero_pay_item_id is None:
            # Future home: apps.xero.models.XeroPayItem (v1: apps.workflow.models;
            # not yet ported to v2).
            from apps.xero.models import XeroPayItem  # noqa: PLC0415

            ordinary_time = XeroPayItem.get_ordinary_time()
            if not ordinary_time:
                raise ValueError(
                    "Cannot create Job: 'Ordinary Time' XeroPayItem not found. "
                    "Run Xero sync or check database seed data."
                )
            self.default_xero_pay_item = ordinary_time

        if is_new:
            # Ensure job_number is generated for new instances before saving
            if self.id is None:
                self.id = uuid.uuid4()
            self.job_number = self.generate_job_number()
            if not self.job_number:
                logger.error("Failed to generate a job number. Cannot save job.")
                raise ValueError("Job number generation failed.")
            logger.debug("Saving new job with job number: %s", self.job_number)

            # To assure all jobs have a priority
            with transaction.atomic():
                default_priority = self._calculate_next_priority_for_status(self.status)
                self.priority = default_priority

                # Create initial CostSet instances (modern system)
                logger.debug("Creating initial CostSet entries.")

                # Initialize summary for new cost sets to avoid serialization errors
                initial_summary = {"cost": 0.0, "rev": 0.0, "hours": 0.0}

                # CostSet.job points at this unsaved Job by UUID. PostgreSQL FK
                # checks are deferrable, so the transaction only needs the Job
                # row to exist by commit time after the save below.
                # Create estimate cost set
                estimate_cost_set = CostSet.objects.create(
                    job_id=self.id,
                    kind="estimate",
                    rev=1,
                    summary=initial_summary,
                )
                self.latest_estimate_id = estimate_cost_set.id

                # Create quote cost set
                quote_cost_set = CostSet.objects.create(
                    job_id=self.id,
                    kind="quote",
                    rev=1,
                    summary=initial_summary,
                )
                self.latest_quote_id = quote_cost_set.id

                # Create actual cost set
                actual_cost_set = CostSet.objects.create(
                    job_id=self.id,
                    kind="actual",
                    rev=1,
                    summary=initial_summary,
                )
                self.latest_actual_id = actual_cost_set.id

                logger.debug("Initial CostSets created successfully.")

                super().save(*args, **kwargs)

                # Seed per-subtype charge-out rates. Shop jobs never bill
                # revenue, so their rates are zero.
                JobLabourRate.objects.bulk_create(
                    JobLabourRate(
                        job_id=self.id,
                        labour_subtype=subtype,
                        charge_out_rate=(
                            Decimal("0.00") if self.shop_job else subtype.default_charge_out_rate
                        ),
                    )
                    for subtype in LabourSubtype.objects.filter(is_active=True)
                )

                # Note: Job creation event is now handled in JobRestService.create_job()
                # to prevent duplicate event creation between model and service layers

        else:
            if original_job is None:
                # Unreachable: is_new False always loads original_job above.
                raise RuntimeError("existing Job row was not loaded for change detection")
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
                side_effect_fields = self._apply_change_side_effects(changes_before, changes_after)
                if side_effect_fields and kwargs.get("update_fields") is not None:
                    kwargs["update_fields"] = list(
                        set(kwargs["update_fields"]) | side_effect_fields
                    )

            with transaction.atomic():
                super().save(*args, **kwargs)
                if changes_before:
                    self._record_change_event(
                        changes_before,
                        changes_after,
                        detail_changes,
                        event_types,
                        staff,
                        enrichment,
                    )
                    self._clear_assigned_staff_on_archive(changes_after)

        # v1 parity: imported at call time to avoid a tasks<->models cycle.
        from apps.job.tasks import request_job_summary_pdf_refresh  # noqa: PLC0415

        request_job_summary_pdf_refresh()

    def get_absolute_url(self) -> str:
        """Front-end URL for this job."""
        from django.conf import settings  # noqa: PLC0415

        # FRONT_END_URL is not yet defined in v2 settings (v1 reads it from the
        # environment), so fetch it dynamically pending the port.
        front_end_url: str = getattr(settings, "FRONT_END_URL", "")
        if not front_end_url:
            raise ValueError("FRONT_END_URL is not configured")
        return f"{front_end_url.rstrip('/')}/jobs/{self.id}"

    @classmethod
    def _calculate_next_priority_for_status(cls, status_value: str) -> float:
        max_entry = (
            cls.objects.filter(status=status_value).aggregate(Max("priority"))["priority__max"]
            or 0.0
        )
        return max_entry + cls.PRIORITY_INCREMENT

    @property
    def shop_job(self) -> bool:
        """Indicates if this is a shop job (belongs to shop company)."""
        if not self.company_id:
            return False

        defaults = CompanyDefaults.get_solo()
        return self.company_id == defaults.shop_company_id

    @shop_job.setter
    def shop_job(self, value: bool) -> None:
        """Set whether this is a shop job by updating the company ID."""
        if value:
            defaults = CompanyDefaults.get_solo()
            self.company_id = defaults.shop_company_id
        else:
            self.company_id = None

    @property
    def quoted(self) -> bool:
        """Whether this job currently has a quote attached."""
        try:
            return self.quote is not None
        # deliberate-swallow: Django raises RelatedObjectDoesNotExist when a
        # reverse one-to-one has no row, and "there is no quote" is precisely
        # the False this predicate exists to return. Rejected the broader
        # AttributeError, which RelatedObjectDoesNotExist also subclasses: it
        # caught a typo'd attribute anywhere in the expression and answered
        # "no quote" — a wrong answer rather than an error.
        except ObjectDoesNotExist:
            return False

    @property
    def accepted_for_work_at(self) -> datetime | None:
        """Timestamp of the first approved (or in_progress) status event."""
        approved_event = (
            self.events.filter(
                delta_after__status="approved",
            )
            .order_by("timestamp")
            .first()
        )
        if approved_event:
            return approved_event.timestamp

        in_progress_event = (
            self.events.filter(
                delta_after__status="in_progress",
            )
            .order_by("timestamp")
            .first()
        )
        if in_progress_event:
            return in_progress_event.timestamp

        return None

    def clean(self) -> None:
        """Validate the min/max people bounds."""
        from django.core.exceptions import ValidationError  # noqa: PLC0415

        errors = {}
        if self.min_people < 1:
            errors["min_people"] = "min_people must be at least 1"
        if self.max_people < 1:
            errors["max_people"] = "max_people must be at least 1"
        if self.max_people < self.min_people:
            errors["max_people"] = "max_people must be >= min_people"
        if errors:
            raise ValidationError(errors)

    def get_latest(self, kind: str) -> CostSet | None:
        """Return the respective CostSet or None.

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
            raise ValueError(f"Invalid kind '{kind}'. Must be one of: {list(field_mapping.keys())}")

        return getattr(self, field_mapping[kind], None)

    def set_latest(self, kind: str, cost_set: CostSet, staff: "Staff") -> None:
        """Update the latest-cost-set pointer and save.

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
            raise ValueError(f"Invalid kind '{kind}'. Must be one of: {list(field_mapping.keys())}")

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
        """Return a formatted display name for the job including company name.

        Format: job_number - (first 12 chars of company name), job_name
        """
        company_name = self.company.name[:12] if self.company else "No Company"
        return f"{self.job_number} - {company_name}, {self.name}"

    @property
    def start_date(self) -> date | None:
        """Return the earliest accounting_date from actual CostLines."""
        earliest: date | None = self.latest_actual.cost_lines.aggregate(
            earliest=Min("accounting_date")
        )["earliest"]
        return earliest

    @property
    def last_financial_activity_date(self) -> date | None:
        """Return the latest accounting_date from actual CostLines."""
        latest: date | None = self.latest_actual.cost_lines.aggregate(
            latest=Max("accounting_date")
        )["latest"]
        return latest

    def generate_job_number(self) -> int:
        """Return the next job number (max of starting number and highest + 1)."""
        company_defaults: CompanyDefaults = CompanyDefaults.get_solo()
        starting_number: int = company_defaults.starting_job_number
        highest_job: int = Job.objects.all().aggregate(Max("job_number"))["job_number__max"] or 0
        return max(starting_number, highest_job + 1)

    # ── Field change tracking ──────────────────────────────────────────
    #
    # All concrete fields are tracked unless listed in UNTRACKED_FIELDS.
    # Fields with custom description logic have handlers in _FIELD_HANDLERS.
    # Any tracked field without a handler gets a generic "X changed" event.

    def _detect_field_changes(
        self, original_job: "Job", update_fields: Iterable[str] | None = None
    ) -> tuple[
        dict[str, _JsonScalar],
        dict[str, _JsonScalar],
        list[dict[str, str]],
        list[str],
    ]:
        """Return (changes_before, changes_after, detail_changes, event_types).

        When update_fields is passed to save(), only those fields are considered —
        in-memory mutations on other fields weren't persisted, so emitting events
        for them would misrepresent what changed on the row.
        """
        changes_before: dict[str, _JsonScalar] = {}
        changes_after: dict[str, _JsonScalar] = {}
        detail_changes: list[dict[str, str]] = []
        event_types: list[str] = []

        restricted = set(update_fields) if update_fields is not None else None

        for field in self._meta.get_fields():
            # Only concrete scalar fields (skip reverse FKs, M2M, generic
            # relations). Concrete fields are exactly the bound models.Field
            # instances (v1 tested `hasattr(field, "attname")`, which holds
            # for every bound Field and for nothing else get_fields returns).
            if not isinstance(field, models.Field) or field.many_to_many:
                continue
            attr = field.attname
            if attr in self.UNTRACKED_FIELDS:
                continue
            if restricted is not None and not (attr in restricted or field.name in restricted):
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
                # Generic detail using field verbose_name (str() forces any
                # lazy proxy; these models use plain-str verbose names)
                label = str(field.verbose_name)
                detail_changes.append(
                    {
                        "field_name": label,
                        "old_value": str(_json_safe(old_val)),
                        "new_value": str(_json_safe(new_val)),
                    }
                )
                event_types.append("job_updated")

        return changes_before, changes_after, detail_changes, event_types

    def _record_change_event(  # noqa: PLR0913, PLR0917 -- Event forensics keep context fields explicit.
        self,
        changes_before: dict[str, _JsonScalar],
        changes_after: dict[str, _JsonScalar],
        detail_changes: list[dict[str, str]],
        event_types: list[str],
        staff: "Staff",
        enrichment: dict[str, Any],
    ) -> None:
        """Create the single JobEvent for a batch of detected field changes."""
        event_type = enrichment.pop("event_type_override", None)
        if not event_type:
            event_type = self._infer_event_type(event_types, changes_after)

        detail: dict[str, Any] = {"changes": detail_changes}
        priority_position = enrichment.get("priority_position")
        if event_type in {"priority_changed", "status_changed"} and priority_position:
            # Float changed but rank didn't — drag was a no-op visually.
            # Skip the JobEvent so we don't pollute the audit log. Log a
            # warning so we can spot it if it starts happening unexpectedly
            # (e.g. a UI bug that fires reorder requests on every click).
            if event_type == "priority_changed" and priority_position.get(
                "old_position"
            ) == priority_position.get("new_position"):
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
            delta_checksum=enrichment.get("delta_checksum") or None,
        )

    def _apply_change_side_effects(
        self,
        changes_before: dict[str, _JsonScalar],  # noqa: ARG002 -- Kept for a symmetric side-effect interface.
        changes_after: dict[str, _JsonScalar],
    ) -> set[str]:
        """Mutate self for non-event side effects and return the fields touched.

        Returned set is used to extend `update_fields` so the mutations reach
        the DB when the caller restricted which fields to save.
        """
        mutated: set[str] = set()
        if changes_after.get("is_urgent") is True:
            from django.db.models import Max  # noqa: PLC0415

            max_p = Job.objects.aggregate(m=Max("priority"))["m"] or 0
            self.priority = max_p + self.PRIORITY_INCREMENT
            mutated.add("priority")
        if "status" in changes_after:
            new_status = changes_after["status"]
            # Set completed_at on first transition to a completed status
            if new_status in ("recently_completed", "archived") and not self.completed_at:
                self.completed_at = timezone.now()
                mutated.add("completed_at")
            # Clear completed_at if moved back to a non-completed status
            elif new_status not in ("recently_completed", "archived") and (
                self.completed_at is not None
            ):
                self.completed_at = None
                mutated.add("completed_at")
        return mutated

    def _clear_assigned_staff_on_archive(self, changes_after: dict[str, _JsonScalar]) -> None:
        if changes_after.get("status") != "archived":
            return

        self.people.clear()

    @staticmethod
    def _infer_event_type(event_types: list[str], changes_after: dict[str, _JsonScalar]) -> str:
        """Pick the most significant event type from collected types."""
        # Rejected flag + archived status → job_rejected
        if changes_after.get("rejected_flag") is True and changes_after.get("status") == "archived":
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
    def _handle_status_change(
        _self_job: "Job", old_status: str, new_status: str
    ) -> tuple[str, dict[str, str]]:
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
    def _handle_company_change(
        self_job: "Job", old_company_id: uuid.UUID | None, new_company_id: uuid.UUID | None
    ) -> tuple[str, dict[str, str]]:
        # Future home: apps.company.models.Company (not yet ported to v2).
        from apps.company.models import Company  # noqa: PLC0415

        old_company = "Shop Job"
        new_company = "Shop Job"
        if old_company_id:
            try:
                old_company = Company.objects.get(id=old_company_id).name
            # deliberate-swallow: a deleted company is real history; a DB error is not
            except Company.DoesNotExist:
                old_company = "Unknown Company"
        if new_company_id:
            new_company = self_job.company.name if self_job.company else "Unknown Company"
        return (
            "company_changed",
            {
                "field_name": "Company",
                "old_value": old_company,
                "new_value": new_company,
            },
        )

    @staticmethod
    def _handle_person_change(
        self_job: "Job", old_person_id: uuid.UUID | None, new_person_id: uuid.UUID | None
    ) -> tuple[str, dict[str, str]]:
        old_person = "None"
        new_person = "None"
        if old_person_id:
            try:
                # Future home: apps.company.models.Person (not yet ported to v2).
                from apps.company.models import Person  # noqa: PLC0415

                old_person = Person.objects.get(id=old_person_id).name
            # deliberate-swallow: a deleted person is real history; a DB error is not
            except Person.DoesNotExist:
                old_person = "Unknown Person"
        if new_person_id:
            new_person = self_job.person.name if self_job.person else "Unknown Person"
        return (
            "person_changed",
            {
                "field_name": "Person",
                "old_value": old_person,
                "new_value": new_person,
            },
        )

    @staticmethod
    def _handle_xero_pay_item_change(
        self_job: "Job", old_pay_item_id: uuid.UUID | None, new_pay_item_id: uuid.UUID | None
    ) -> tuple[str, dict[str, str]]:
        # Future home: apps.xero.models.XeroPayItem (v1: apps.workflow.models;
        # not yet ported to v2).
        from apps.xero.models import XeroPayItem  # noqa: PLC0415

        old_name = "None"
        new_name = "None"
        if old_pay_item_id:
            try:
                old_name = XeroPayItem.objects.get(id=old_pay_item_id).name
            # deliberate-swallow: a deleted pay item is real history; a DB error is not
            except XeroPayItem.DoesNotExist:
                old_name = "Unknown"
        if new_pay_item_id:
            new_name = (
                self_job.default_xero_pay_item.name if self_job.default_xero_pay_item else "Unknown"
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
    def _handle_text_field_change(
        event_type: str, field_display_name: str
    ) -> "Callable[[Job, str | None, str | None], tuple[str, dict[str, str]] | None]":
        """Return a handler for text field changes (factory)."""

        def handler(
            _self_job: "Job", old_value: str | None, new_value: str | None
        ) -> tuple[str, dict[str, str]] | None:
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
    def _handle_date_change(
        event_type: str, field_display_name: str
    ) -> "Callable[[Job, date | None, date | None], tuple[str, dict[str, str]]]":
        """Return a handler for date field changes (factory)."""

        def handler(
            _self_job: "Job", old_date: date | None, new_date: date | None
        ) -> tuple[str, dict[str, str]]:
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
    def _handle_quote_acceptance_change(
        _self_job: "Job", old_date: datetime | None, new_date: datetime | None
    ) -> tuple[str, dict[str, str]] | None:
        if not old_date and new_date:
            return (
                "quote_accepted",
                {
                    "field_name": "Quote acceptance date",
                    "old_value": "None",
                    "new_value": new_date.strftime("%Y-%m-%d at %H:%M"),
                },
            )
        if old_date and not new_date:
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
    def _handle_pricing_methodology_change(
        _self_job: "Job", old_method: str, new_method: str
    ) -> tuple[str, dict[str, str]]:
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
    def _handle_speed_quality_tradeoff_change(
        _self_job: "Job", old_tradeoff: str, new_tradeoff: str
    ) -> tuple[str, dict[str, str]]:
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
    def _handle_rdti_type_change(
        _self_job: "Job", old_type: str | None, new_type: str | None
    ) -> tuple[str, dict[str, str]]:
        # Equivalent to v1's `.get(old_type, old_type or "None")`: a falsy key
        # can never be in choices, so it always resolved to "None".
        choices = dict(RDTIType.choices)
        old_display = choices.get(old_type, old_type) if old_type else "None"
        new_display = choices.get(new_type, new_type) if new_type else "None"
        return (
            "job_updated",
            {
                "field_name": "RDTI classification",
                "old_value": str(old_display),
                "new_value": str(new_display),
            },
        )

    # Maps field attname → handler(self_job, old, new) → (event_type, detail_dict) | None
    # Fields not listed here get a generic detail via verbose_name.
    # (staticmethod objects are directly callable on Python >= 3.10, so no
    # `.__func__` unwrapping is needed in the class body.)
    _FIELD_HANDLERS: ClassVar[dict[str, Callable[..., tuple[str, dict[str, str]] | None]]] = {
        "status": _handle_status_change,
        "name": lambda _self, old, new: (
            "job_updated",
            {"field_name": "Job name", "old_value": str(old), "new_value": str(new)},
        ),
        "company_id": _handle_company_change,
        "person_id": _handle_person_change,
        "order_number": lambda _self, old, new: (
            "job_updated",
            {
                "field_name": "Order number",
                "old_value": str(old or "None"),
                "new_value": str(new or "None"),
            },
        ),
        "description": _handle_text_field_change("job_updated", "Job description"),
        "notes": _handle_text_field_change("notes_updated", "Internal notes"),
        "delivery_date": _handle_date_change("delivery_date_changed", "Delivery date"),
        "quote_acceptance_date": _handle_quote_acceptance_change,
        "pricing_methodology": _handle_pricing_methodology_change,
        "speed_quality_tradeoff": _handle_speed_quality_tradeoff_change,
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
        "paid": _handle_boolean_change(
            "payment_received",
            "payment_updated",
            "Paid",
        ),
        "foreman_signed_off": _handle_boolean_change(
            "completion_checklist_updated",
            "completion_checklist_updated",
            "Foreman sign-off",
        ),
        "timesheets_collected": _handle_boolean_change(
            "completion_checklist_updated",
            "completion_checklist_updated",
            "Timesheets collected",
        ),
        "materials_checked": _handle_boolean_change(
            "completion_checklist_updated",
            "completion_checklist_updated",
            "Materials checked",
        ),
        "customer_called": _handle_boolean_change(
            "completion_checklist_updated",
            "completion_checklist_updated",
            "Customer called",
        ),
        "released": _handle_boolean_change(
            "completion_checklist_updated",
            "completion_checklist_updated",
            "Job released",
        ),
        "complex_job": _handle_boolean_change(
            "job_updated",
            "job_updated",
            "Complex job",
        ),
        "is_urgent": _handle_boolean_change(
            "urgent_flagged",
            "urgent_cleared",
            "Urgent job",
        ),
        "rdti_type": _handle_rdti_type_change,
        "default_xero_pay_item_id": _handle_xero_pay_item_change,
    }
