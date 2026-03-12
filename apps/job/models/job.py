import logging
import uuid
from datetime import date, datetime
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


class Job(models.Model):
    # CHECKLIST - when adding a new field or property to Job, check these locations:
    #   1. JOB_DIRECT_FIELDS below (if it's a model field)
    #   2. _create_change_events() field_handlers dict in this file
    #   3. JobSerializer.Meta.fields in apps/job/serializers/job_serializer.py
    #   4. ClientJobHeaderSerializer in apps/client/serializers.py
    #   5. get_client_jobs() response dict in apps/client/services/client_rest_service.py
    #   6. KanbanService.serialize_job_for_api() in apps/job/services/kanban_service.py
    #   7. KanbanJobSerializer and KanbanColumnJobSerializer in apps/job/serializers/kanban_serializer.py
    #   8. original_values dict in JobRestService.update_job() in apps/job/services/job_rest_service.py
    #   9. data_quality_report.py in apps/job/services/
    #  10. JobAgingService job_info dict in apps/accounting/services.py
    #  11. serialize_job_list() in apps/workflow/api/reports/job_movement.py
    #  12. get_jobs_for_dropdown() in apps/job/utils.py
    #  13. jobs_data dict in apps/purchasing/views/purchasing_rest_views.py
    #  14. job_metrics dict in JobRestService.get_weekly_metrics() in apps/job/services/job_rest_service.py
    #  15. job_data dict in DailyTimesheetService._get_job_breakdown() in apps/timesheet/services/daily_timesheet_service.py
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
    ]

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

    history: HistoricalRecords = HistoricalRecords(table_name="workflow_historicaljob")

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
        db_table = "workflow_job"
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

    def set_latest(self, kind: str, cost_set: "CostSet") -> None:
        """
        Updates pointer and saves.

        Args:
            kind: 'estimate', 'quote' or 'actual'
            cost_set: CostSet instance to set as latest
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
        self.save(update_fields=[field_mapping[kind]])

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

        is_new = self._state.adding
        original_job = None

        # Track original values for change detection
        if not is_new:
            original_job = Job.objects.get(pk=self.pk)

        if (staff and is_new) or (not self.created_by and staff):
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
            # Dynamic change detection for existing jobs
            if staff:
                self._create_change_events(original_job, staff)

            # Save the job first
            super(Job, self).save(*args, **kwargs)

    def _create_change_events(self, original_job, staff):
        """
        Dynamically detect field changes and create appropriate events.
        """
        # Store staff for use in handlers
        self._current_staff = staff

        # Field mapping: field_name -> description_generator_function
        field_handlers = {
            "status": self._handle_status_change,
            "name": lambda old, new: (
                "job_updated",
                f"Job name changed from '{old}' to '{new}'",
            ),
            "client_id": self._handle_client_change,
            "contact_id": self._handle_contact_change,
            "order_number": lambda old, new: (
                "job_updated",
                f"Order number changed from '{old or 'None'}' to '{new or 'None'}'",
            ),
            "description": self._handle_text_field_change(
                "Job description", "job_updated"
            ),
            "notes": self._handle_text_field_change("Internal notes", "notes_updated"),
            "delivery_date": self._handle_date_change(
                "delivery_date_changed", "Delivery date"
            ),
            "quote_acceptance_date": self._handle_quote_acceptance_change,
            "pricing_methodology": self._handle_pricing_methodology_change,
            "speed_quality_tradeoff": self._handle_speed_quality_tradeoff_change,
            "charge_out_rate": lambda old, new: (
                "pricing_changed",
                f"Charge out rate changed from ${old}/hour to ${new}/hour",
            ),
            "price_cap": lambda old, new: (
                "pricing_changed",
                f"Price cap changed from ${old or 'None'} to ${new or 'None'}",
            ),
            "priority": lambda old, new: (
                "priority_changed",
                f"Job priority changed from {old} to {new}. This affects the job's position in the workflow queue",
            ),
            "paid": self._handle_boolean_change(
                "payment_received",
                "payment_updated",
                "Job marked as PAID. Payment has been received from client",
                "Job payment status changed to UNPAID",
            ),
            "collected": self._handle_boolean_change(
                "job_collected",
                "collection_updated",
                "Job marked as COLLECTED. Work has been picked up by client",
                "Job collection status changed to NOT COLLECTED",
            ),
            "complex_job": self._handle_boolean_change(
                "job_updated",
                "job_updated",
                "Job marked as COMPLEX JOB. This job requires special attention or has complex requirements",
                "Job no longer marked as complex job",
            ),
            "rdti_type": self._handle_rdti_type_change,
            "default_xero_pay_item_id": self._handle_xero_pay_item_change,
        }

        for field_name, handler in field_handlers.items():
            old_value = getattr(original_job, field_name)
            new_value = getattr(self, field_name)

            if old_value != new_value:
                if callable(handler):
                    result = handler(old_value, new_value)
                    if result:  # Handler can return None to skip event creation
                        event_type, description = result
                        JobEvent.objects.create(
                            job=self,
                            event_type=event_type,
                            description=description,
                            staff=staff,
                        )

    def _handle_status_change(self, old_status, new_status):
        """Handle status change with special logic for rejected jobs."""
        old_display = dict(self.JOB_STATUS_CHOICES).get(old_status, old_status)
        new_display = dict(self.JOB_STATUS_CHOICES).get(new_status, new_status)

        # Create status change event
        JobEvent.objects.create(
            job=self,
            event_type="status_changed",
            description=f"Status changed from '{old_display}' to '{new_display}'. Job moved to new workflow stage.",
            staff=self._current_staff,
        )

        # Set completed_at on first transition to a completed status
        if new_status in ("recently_completed", "archived") and not self.completed_at:
            self.completed_at = timezone.now()

        # Clear completed_at if moved back to a non-completed status
        if new_status not in ("recently_completed", "archived"):
            self.completed_at = None

        # Special handling for rejected jobs
        if (
            new_status == "archived"
            and hasattr(self, "rejected_flag")
            and self.rejected_flag
        ):
            JobEvent.objects.create(
                job=self,
                event_type="job_rejected",
                description="Job marked as rejected. Quote was declined by client.",
                staff=self._current_staff,
            )

        return None  # Already handled, don't create another event

    def _handle_client_change(self, old_client_id, new_client_id):
        """Handle client change with proper name resolution."""
        old_client = "Shop Job"
        new_client = "Shop Job"

        if old_client_id:
            try:

                old_client = Client.objects.get(id=old_client_id).name
            except Exception:
                old_client = "Unknown Client"

        if new_client_id:
            new_client = self.client.name if self.client else "Unknown Client"

        return (
            "client_changed",
            f"Client changed from '{old_client}' to '{new_client}'",
        )

    def _handle_contact_change(self, old_contact_id, new_contact_id):
        """Handle contact change with proper name resolution."""
        old_contact = "None"
        new_contact = "None"

        if old_contact_id:
            try:
                from apps.client.models import ClientContact

                old_contact = ClientContact.objects.get(id=old_contact_id).name
            except Exception:
                old_contact = "Unknown Contact"

        if new_contact_id:
            new_contact = self.contact.name if self.contact else "Unknown Contact"

        return (
            "contact_changed",
            f"Primary contact changed from '{old_contact}' to '{new_contact}'",
        )

    def _handle_xero_pay_item_change(self, old_pay_item_id, new_pay_item_id):
        """Handle Xero pay item change with proper name resolution."""
        old_name = "None"
        new_name = "None"

        if old_pay_item_id:
            try:
                old_name = XeroPayItem.objects.get(id=old_pay_item_id).name
            except Exception:
                old_name = "Unknown"

        if new_pay_item_id:
            new_name = (
                self.default_xero_pay_item.name
                if self.default_xero_pay_item
                else "Unknown"
            )

        return (
            "job_updated",
            f"Xero pay item changed from '{old_name}' to '{new_name}'",
        )

    def _handle_text_field_change(self, field_display_name, event_type):
        """Factory function for handling text field changes."""

        def handler(old_value, new_value):
            if old_value and new_value:
                truncated = (
                    (old_value[:50] + "...") if len(old_value) > 50 else old_value
                )
                return (
                    event_type,
                    f"{field_display_name} updated. Previous content: '{truncated}'",
                )
            elif not old_value and new_value:
                truncated = (
                    (new_value[:100] + "...") if len(new_value) > 100 else new_value
                )
                return (event_type, f"{field_display_name} added: '{truncated}'")
            elif old_value and not new_value:
                truncated = (
                    (old_value[:50] + "...") if len(old_value) > 50 else old_value
                )
                return (
                    event_type,
                    f"{field_display_name} removed. Previous content: '{truncated}'",
                )
            return None

        return handler

    def _handle_date_change(self, event_type, field_display_name):
        """Factory function for handling date field changes."""

        def handler(old_date, new_date):
            old_str = old_date.strftime("%Y-%m-%d") if old_date else "None"
            new_str = new_date.strftime("%Y-%m-%d") if new_date else "None"
            return (
                event_type,
                f"{field_display_name} changed from '{old_str}' to '{new_str}'",
            )

        return handler

    def _handle_quote_acceptance_change(self, old_date, new_date):
        """Handle quote acceptance date with special logic."""
        if not old_date and new_date:
            return (
                "quote_accepted",
                f"Quote accepted by client on {new_date.strftime('%Y-%m-%d at %H:%M')}",
            )
        elif old_date and not new_date:
            return (
                "job_updated",
                f"Quote acceptance date removed. Was previously accepted on {old_date.strftime('%Y-%m-%d')}",
            )
        return None

    def _handle_pricing_methodology_change(self, old_method, new_method):
        """Handle pricing methodology change with display names."""
        old_display = dict(self.PRICING_METHODOLOGY_CHOICES).get(old_method, old_method)
        new_display = dict(self.PRICING_METHODOLOGY_CHOICES).get(new_method, new_method)
        return (
            "pricing_changed",
            f"Pricing methodology changed from '{old_display}' to '{new_display}'",
        )

    def _handle_speed_quality_tradeoff_change(self, old_tradeoff, new_tradeoff):
        """Handle speed/quality tradeoff change with display names."""
        old_display = dict(SpeedQualityTradeoff.choices).get(old_tradeoff, old_tradeoff)
        new_display = dict(SpeedQualityTradeoff.choices).get(new_tradeoff, new_tradeoff)
        return (
            "job_updated",
            f"Speed/quality tradeoff changed from '{old_display}' to '{new_display}'",
        )

    def _handle_rdti_type_change(self, old_type, new_type):
        """Handle RDTI type change with display names."""
        old_display = dict(RDTIType.choices).get(old_type, old_type or "None")
        new_display = dict(RDTIType.choices).get(new_type, new_type or "None")
        return (
            "job_updated",
            f"RDTI classification changed from '{old_display}' to '{new_display}'",
        )

    def _handle_boolean_change(self, true_event, false_event, true_desc, false_desc):
        """Factory function for handling boolean field changes."""

        def handler(old_value, new_value):
            if new_value and not old_value:
                return (true_event, true_desc)
            elif old_value and not new_value:
                return (false_event, false_desc)
            return None

        return handler
