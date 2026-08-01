"""Core models ported from v1's ``apps/workflow/models/`` (the dissolved grab-bag app).

Per the v2 porting rules, models that leave v1's ``workflow`` app pin
``Meta.db_table = "workflow_<modelname>"`` so their tables do not move — v2.0
data migrates by pg_dump/restore, so column names and nullability must stay
bit-identical to v1. That parity requirement is why ``null=True`` on string
fields is kept verbatim (``# noqa: DJ001`` at each site).

Not ported here (they belong to apps above core in the layer contract):

- ``XeroError`` (multi-table child of AppError) — goes to the xero integration app.
- ``CompanyDefaults.llm_api_key`` property — depends on ``AIProvider`` (apps.ai).
- ``AppError.session_replay`` FK — target model ``SessionReplayRecording`` goes to
  the diagnostics app; the column survives as a plain UUID field (see AppError).
"""

import logging
import secrets
import uuid
from collections.abc import Iterable
from decimal import Decimal
from typing import ClassVar, Protocol, cast

from django.apps import apps as django_apps
from django.contrib.auth.base_user import AbstractBaseUser
from django.db import models
from django.db.models.base import ModelBase
from django.utils import timezone
from solo.models import SingletonModel

# Starting point for an installation that has not had its terms written yet.
# Real wording is seeded per client by the fixtures and edited in Company Settings.
DEFAULT_XERO_QUOTE_TERMS = "Terms of trade can be found on our website."


class AppError(models.Model):  # noqa: DJ008  # v1 parity: AppError defines no __str__
    """Persistent record of an application error (ADR 0019)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    timestamp = models.DateTimeField(auto_now_add=True)
    message = models.TextField()
    data = models.JSONField(blank=True, null=True)

    # Code location fields for filtering
    app = models.CharField(max_length=50, blank=True, null=True)  # noqa: DJ001
    file = models.CharField(max_length=200, blank=True, null=True)  # noqa: DJ001
    function = models.CharField(max_length=100, blank=True, null=True)  # noqa: DJ001
    severity = models.IntegerField(default=logging.ERROR)

    # Commonly filtered business context (separate fields)
    job_id = models.UUIDField(blank=True, null=True)
    user_id = models.UUIDField(blank=True, null=True)
    # v1: ForeignKey("workflow.SessionReplayRecording", SET_NULL, related_name=
    # "app_errors"). SessionReplayRecording belongs to the diagnostics app, which
    # sits ABOVE core in the layer contract, so core cannot hold the FK. The
    # column name and type match v1's FK column exactly; the diagnostics port
    # owns restoring the FK constraint (and the v1 existence validation in
    # apps.core.errors._clean_session_replay_id).
    session_replay_id = models.UUIDField(blank=True, null=True)

    # Error resolution tracking
    resolved = models.BooleanField(default=False)
    resolved_by = models.ForeignKey(
        "accounts.Staff", on_delete=models.PROTECT, blank=True, null=True
    )
    resolved_timestamp = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = "workflow_apperror"
        ordering: ClassVar[list[str]] = ["-timestamp"]
        verbose_name = "Application Error"
        verbose_name_plural = "Application Errors"
        indexes: ClassVar[list[models.Index]] = [
            models.Index(
                fields=["timestamp", "severity"],
                name="workflow_apperror_time_sev_idx",
            ),  # Common: recent errors by severity
            models.Index(
                fields=["resolved", "timestamp"],
                name="workflow_apperror_res_time_idx",
            ),  # Common: unresolved errors chronologically
            models.Index(
                fields=["app", "severity"],
                name="workflow_apperror_app_sev_idx",
            ),  # Common: errors by app section
            models.Index(
                fields=["session_replay_id", "timestamp"],
                name="workflow_aperr_replay_time_idx",
            ),
        ]

    def mark_resolved(self, staff_member: AbstractBaseUser) -> None:
        """Mark this error as resolved by the given staff member.

        The parameter is typed as the auth base class because core sits below
        accounts in the layer contract and must not import ``Staff``; the
        assignment goes through the FK's id attribute, which does not need the
        concrete class.
        """
        self.resolved = True
        self.resolved_by_id = staff_member.pk
        self.resolved_timestamp = timezone.now()
        self.save()

    def mark_unresolved(self, staff_member: AbstractBaseUser) -> None:
        """Remove the resolved flag."""
        self.resolved = False
        self.resolved_by = None
        self.resolved_timestamp = None
        self.save()


class _WageBearingStaff(Protocol):
    """Structural view of accounts.Staff used by the wage-rate recompute.

    core cannot import accounts (layer contract), so the recompute goes through
    the app registry and this protocol carries the typing contract.
    """

    base_wage_rate: Decimal
    wage_rate: Decimal

    def save(self, *, update_fields: Iterable[str] | None = None) -> None: ...


class CompanyDefaults(SingletonModel):
    """Singleton company configuration (django-solo), ported verbatim from v1."""

    company_name = models.CharField(max_length=255)
    company_acronym = models.CharField(  # noqa: DJ001
        max_length=10,
        null=True,
        blank=True,
        help_text="Short acronym for the company (e.g., 'MSM' for Morris Sheetmetal)",
    )
    time_markup = models.DecimalField(max_digits=5, decimal_places=2, default=0.3)
    materials_markup = models.DecimalField(max_digits=5, decimal_places=2, default=0.2)
    gst_rate = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        default=Decimal("0.1500"),
        help_text=(
            "Sales tax rate applied to amounts DocketWorks quotes before Xero has "
            "issued an invoice, as a fraction (0.1500 = 15% NZ GST). Xero remains "
            "authoritative for tax on invoices that exist."
        ),
    )
    wage_rate = models.DecimalField(max_digits=6, decimal_places=2, default=32.00)  # rate per hour
    # Approximate payroll loading: 8% annual leave, ~6% public holidays,
    # ~4% sick leave, ~2% ACC, 0% ESCT.
    annual_leave_loading = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=20.00,
        help_text="Percentage added to base_wage_rate to get costing wage_rate (20.00 = 20%)",
    )
    workshop_efficiency_factor = models.DecimalField(
        max_digits=4,
        decimal_places=3,
        default=Decimal("0.750"),
        help_text=(
            "Fraction of clocked workshop hours that count as schedulable "
            "productive output (e.g. 0.750 = 75%). Accounts for breaks, "
            "tool changes, idle time. Applied to per-day capacity in the "
            "workshop scheduler after subtracting booked time/leave."
        ),
    )
    financial_year_start_month = models.IntegerField(
        default=4,
        help_text="Month the financial year starts (1=January, 4=April, 7=July, etc.)",
    )

    starting_job_number = models.IntegerField(
        default=1,
        help_text="Helper field to set the starting job number based on the latest paper job",
    )
    starting_po_number = models.IntegerField(
        default=1, help_text="Helper field to set the starting purchase order number"
    )
    po_prefix = models.CharField(
        max_length=10,
        default="PO-",
        help_text="Prefix for purchase order numbers (e.g., PO-, JO-)",
    )

    # Google Sheets integration for Job Quotes
    master_quote_template_url = models.URLField(  # noqa: DJ001
        null=True,
        blank=True,
        help_text="URL to the master Google Sheets quote template",
    )

    master_quote_template_id = models.CharField(  # noqa: DJ001
        null=True,
        blank=True,
        help_text="Google Sheets ID for the quote template",
        max_length=100,
    )

    gdrive_quotes_folder_url = models.URLField(  # noqa: DJ001
        null=True,
        blank=True,
        help_text="URL to the Google Drive folder for storing quotes",
    )

    gdrive_quotes_folder_id = models.CharField(  # noqa: DJ001
        null=True,
        blank=True,
        help_text="Google Drive folder ID for storing quotes",
        max_length=100,
    )

    # Google Shared Drive — Operations Manual folder hierarchy
    google_shared_drive_id = models.CharField(  # noqa: DJ001
        max_length=100,
        null=True,
        blank=True,
        help_text="Google Shared Drive ID for the company shared drive",
    )
    gdrive_how_we_work_folder_id = models.CharField(  # noqa: DJ001
        max_length=100,
        null=True,
        blank=True,
        help_text="Folder ID for '01 - How we work' (policies, basics)",
    )
    gdrive_sops_folder_id = models.CharField(  # noqa: DJ001
        max_length=100,
        null=True,
        blank=True,
        help_text="Folder ID for '02 - SOPs' (standard operating procedures)",
    )
    gdrive_reference_library_folder_id = models.CharField(  # noqa: DJ001
        max_length=100,
        null=True,
        blank=True,
        help_text="Folder ID for '03 - Reference Library' (reference documents, forms, registers)",
    )

    # Xero integration
    accounting_provider = models.CharField(
        max_length=20,
        default="xero",
        help_text="Active accounting integration: 'xero' or 'myob'",
    )
    xero_tenant_id = models.CharField(  # noqa: DJ001
        max_length=100,
        null=True,
        blank=True,
        help_text="The Xero tenant ID to use for this company",
    )
    xero_shortcode = models.CharField(  # noqa: DJ001
        max_length=20,
        null=True,
        blank=True,
        help_text="Xero organisation shortcode for deep linking (e.g., '!8-5Xl')",
    )
    xero_sales_branding_theme_id = models.UUIDField(
        null=True,
        blank=True,
        verbose_name="Xero sales branding theme",
        help_text=(
            "Controls the layout and presentation of every quote and sales invoice "
            "created in Xero. It is configured during Xero setup and required "
            "before sales documents can be created."
        ),
    )
    xero_quote_terms = models.TextField(
        max_length=4000,
        default=DEFAULT_XERO_QUOTE_TERMS,
        verbose_name="Xero quote terms",
        help_text=(
            "Terms sent on every quote created by DocketWorks. Required — Xero does "
            "not apply its own Terms (Quotes) default to quotes created through the "
            "API. Copy the same text to Xero's Terms (Quotes) setting so quotes "
            "created directly in Xero during an outage use the same terms."
        ),
    )
    enable_xero_sync = models.BooleanField(
        default=True,
        help_text=(
            "Gate for Xero sync. Defaults True (prod). Dev fixture sets False; "
            "seed_xero_from_database sets True after prod IDs are cleared."
        ),
    )
    xero_automated_day_floor = models.PositiveIntegerField(
        default=100,
        help_text=(
            "Reserve this many Xero daily API calls for user-initiated work. "
            "Automated sync aborts when the active Xero app reports remaining "
            "daily calls at or below this value."
        ),
    )

    # Xero Payroll configuration
    # Note: Leave type IDs and earnings rate names are synced to XeroPayItem model
    xero_payroll_calendar_name = models.CharField(
        max_length=100,
        default="Weekly",
        help_text="Name of Xero Payroll calendar to use (e.g., 'Weekly 2025')",
    )
    xero_payroll_calendar_id = models.UUIDField(
        null=True,
        blank=True,
        help_text="Cached Xero Payroll calendar ID (set by xero --setup command)",
    )
    xero_payroll_start_date = models.DateField(
        null=True,
        blank=True,
        help_text="Date Xero payroll went live — reconciliation ignores data before this",
    )

    # Whether to show Sat/Sun columns in timesheet views (admin-togglable)
    weekend_timesheets_enabled = models.BooleanField(
        default=False,
        help_text=(
            "Show Saturday and Sunday in timesheet views (7-day week). Off = 5-day Mon-Fri."
        ),
    )
    job_delta_soft_fail = models.BooleanField(
        default=True,
        help_text=(
            "When enabled, job delta checksum mismatches are logged and recorded "
            "without blocking the save. Disable to reject stale updates."
        ),
    )

    # Default working hours (Mon-Fri, 7am - 3pm)
    mon_start = models.TimeField(default="07:00")
    mon_end = models.TimeField(default="15:00")
    tue_start = models.TimeField(default="07:00")
    tue_end = models.TimeField(default="15:00")
    wed_start = models.TimeField(default="07:00")
    wed_end = models.TimeField(default="15:00")
    thu_start = models.TimeField(default="07:00")
    thu_end = models.TimeField(default="15:00")
    fri_start = models.TimeField(default="07:00")
    fri_end = models.TimeField(default="15:00")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_xero_sync = models.DateTimeField(
        null=True, blank=True, help_text="The last time Xero data was synchronized"
    )
    last_xero_deep_sync = models.DateTimeField(
        null=True,
        blank=True,
        help_text="The last time a deep Xero sync was performed (looking back 90 days)",
    )

    # Company address (used for employee records, documents, etc.)
    address_line1 = models.CharField(  # noqa: DJ001
        max_length=255,
        null=True,
        blank=True,
        help_text="Street address line 1",
    )
    address_line2 = models.CharField(  # noqa: DJ001
        max_length=255,
        null=True,
        blank=True,
        help_text="Street address line 2 (optional)",
    )
    suburb = models.CharField(  # noqa: DJ001
        max_length=100,
        null=True,
        blank=True,
        help_text="Suburb (for NZ addresses)",
    )
    city = models.CharField(  # noqa: DJ001
        max_length=100,
        null=True,
        blank=True,
        help_text="City",
    )
    post_code = models.CharField(  # noqa: DJ001
        max_length=20,
        null=True,
        blank=True,
        help_text="Postal/ZIP code",
    )
    country = models.CharField(
        max_length=100,
        default="New Zealand",
        help_text="Country name",
    )
    company_email = models.EmailField(  # noqa: DJ001
        null=True,
        blank=True,
        help_text="Company contact email address",
    )
    company_url = models.URLField(  # noqa: DJ001
        null=True,
        blank=True,
        help_text="Company website URL",
    )
    logo = models.ImageField(
        upload_to="company_logos/",
        null=True,
        blank=True,
        help_text="Company logo (square/standard)",
    )
    logo_wide = models.ImageField(
        upload_to="company_logos/",
        null=True,
        blank=True,
        help_text="Wide company logo for letterheads and PDFs",
    )

    # Phase 2: shop_company FK to company.Company is restored when the company
    # app's models land (v1 parity requires it; the app doesn't exist yet).

    # Test company configuration
    test_company_name = models.CharField(  # noqa: DJ001
        max_length=255,
        null=True,
        blank=True,
        help_text=(
            "Name of the test company used for testing (e.g., 'ABC Carpet Cleaning "
            "TEST IGNORE'). This company's name is preserved during data backports."
        ),
    )

    # KPI thresholds — all daily unless noted otherwise
    kpi_daily_billable_hours_green = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        verbose_name="Daily billable hours (green)",
        help_text="Daily total billable hours across all staff above which the day is green",
    )
    kpi_daily_billable_hours_amber = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        verbose_name="Daily billable hours (amber)",
        help_text="Daily total billable hours across all staff above which the day is amber",
    )
    kpi_daily_gp_target = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        verbose_name="Daily gross profit target",
        help_text="Daily gross profit target in dollars",
    )
    kpi_daily_shop_hours_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        verbose_name="Daily shop hours percentage target",
        help_text="Target percentage of daily hours spent on shop (non-billable) jobs",
    )
    kpi_job_gp_target_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        verbose_name="Target GP % per job",
        help_text="Target gross profit percentage for individual jobs",
    )
    kpi_daily_gp_green = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        verbose_name="Daily GP (green)",
        help_text="Daily gross profit above which the day is green",
    )
    kpi_daily_gp_amber = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        verbose_name="Daily GP (amber)",
        help_text="Daily gross profit above which the day is amber",
    )
    daily_approved_hours_target = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        verbose_name="Daily approved hours target",
        help_text=(
            "Target daily hours of newly-approved work flowing into the shop, "
            "used by the Sales Pipeline scoreboard"
        ),
    )

    class Meta:
        db_table = "workflow_companydefaults"
        verbose_name = "Company Defaults"
        verbose_name_plural = "Company Defaults"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=models.Q(id=1),
                name="companydefaults_singleton",
            ),
        ]

    def __str__(self) -> str:
        return self.company_name

    def save(
        self,
        *,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        # Check if annual_leave_loading changed - if so, recompute all staff wage_rates
        loading_changed = False
        if self.pk:
            try:
                old = CompanyDefaults.objects.get(pk=self.pk)
                loading_changed = old.annual_leave_loading != self.annual_leave_loading
            except CompanyDefaults.DoesNotExist:
                pass

        super().save(
            force_insert=force_insert,
            force_update=force_update,
            using=using,
            update_fields=update_fields,
        )

        if loading_changed:
            self._recompute_all_staff_wage_rates()

    @classmethod
    def set_xero_sync_enabled(cls, *, enabled: bool) -> None:
        """Persist the Xero sync gate and refresh django-solo's shared cache."""
        company_defaults = cls.objects.get(pk=cls.singleton_instance_id)
        company_defaults.enable_xero_sync = enabled
        company_defaults.save(update_fields=["enable_xero_sync"])

    def _recompute_all_staff_wage_rates(self) -> None:
        """Bulk-recompute wage_rate for all staff based on current annual_leave_loading."""
        # App-registry lookup instead of `from apps.accounts.models import Staff`:
        # core sits below accounts in the layer contract, so even a function-level
        # import is off-limits. The cast to the protocol carries the field typing.
        staff_model = django_apps.get_model("accounts", "Staff")
        loading_multiplier = Decimal("1") + self.annual_leave_loading / Decimal("100")
        staff_rows = cast(
            "Iterable[_WageBearingStaff]",
            staff_model._default_manager.filter(base_wage_rate__gt=0),
        )
        for staff in staff_rows:
            staff.wage_rate = (staff.base_wage_rate * loading_multiplier).quantize(Decimal("0.01"))
            staff.save(update_fields=["wage_rate", "updated_at"])

    # v1's ``llm_api_key`` property (the active AIProvider's key) is NOT ported:
    # AIProvider belongs to the future apps.ai integration app, which sits above
    # core in the layer contract. The ai port owns re-homing that lookup.


class ServiceAPIKey(models.Model):
    """API key for service-level authentication (e.g., chatbot MCP access)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, help_text="Service name (e.g., 'Chatbot Service')")
    key = models.CharField(max_length=64, unique=True, help_text="API key for authentication")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "workflow_serviceapikey"
        verbose_name = "Service API Key"
        verbose_name_plural = "Service API Keys"

    def __str__(self) -> str:
        return f"{self.name} ({'Active' if self.is_active else 'Inactive'})"

    def save(
        self,
        *,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        if not self.key:
            self.key = self.generate_api_key()
        super().save(
            force_insert=force_insert,
            force_update=force_update,
            using=using,
            update_fields=update_fields,
        )

    @staticmethod
    def generate_api_key() -> str:
        """Generate a secure random API key."""
        return secrets.token_urlsafe(48)  # 64 character base64url string

    def mark_used(self) -> None:
        """Mark this API key as recently used."""
        self.last_used = timezone.now()
        self.save(update_fields=["last_used"])
