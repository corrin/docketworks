"""Core models shared by every domain.

Models stored in ``workflow_*`` tables pin those names because data restores
depend on stable database identifiers. Integration models with their own
runtime state (``XeroApp``, ``AIProvider``) remain in their owning apps;
install-level credentials live here on ``IntegrationSettings`` because every
layer reads them (ADR 0053). ``AppError.session_replay`` uses a string
reference so core does not import diagnostics.
"""

import logging
import secrets
import uuid
from collections.abc import Iterable
from decimal import ROUND_HALF_UP, Decimal
from typing import ClassVar, Protocol, cast

from django.apps import apps as django_apps
from django.contrib.auth.base_user import AbstractBaseUser
from django.core.exceptions import ImproperlyConfigured
from django.db import models
from django.db.models.base import ModelBase
from django.utils import timezone
from solo.models import SingletonModel

# Starting point for an installation that has not had its terms written yet.
# Real wording is seeded per client by the fixtures and edited in Company Settings.
DEFAULT_XERO_QUOTE_TERMS = "Terms of trade can be found on our website."


class AppError(models.Model):  # noqa: DJ008  # callers use explicit error fields
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
    # SessionReplayRecording belongs above core in the layer contract; the
    # string reference keeps imports legal while preserving the database FK.
    session_replay = models.ForeignKey(
        "diagnostics.SessionReplayRecording",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="app_errors",
    )

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
                fields=["session_replay", "timestamp"],
                name="workflow_aperr_replay_time_idx",
            ),
        ]
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(condition=~models.Q(app=""), name="app_not_blank"),
            models.CheckConstraint(condition=~models.Q(file=""), name="file_not_blank"),
            models.CheckConstraint(condition=~models.Q(function=""), name="function_not_blank"),
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

    def mark_unresolved(self) -> None:
        """Remove the resolved flag."""
        self.resolved = False
        self.resolved_by = None
        self.resolved_timestamp = None
        self.save()


class IntegrationSettings(models.Model):
    """The credentials and switches this install uses to reach external services.

    One typed column per credential (ADR 0053): mypy sees every read, each
    column carries its own not-blank constraint, and the set of integrations
    is in code rather than data. It holds what the install has exactly one of
    — N-of integrations (``XeroApp``, ``AIProvider``, ``SupplierCredential``)
    keep their own tables. Never ``CompanyDefaults``: its GET is any-staff boot
    data that echoes every column.

    Plaintext by decision (2026-08-01): field-level encryption was dropped in
    v2 because per-instance databases owned by per-client roles make it
    key-management theatre. The scrubber truncates this table whole, so no
    secret reaches a non-production dump.
    """

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)

    # Google Places (New), read by apps/core/geocoding.
    google_maps_api_key = models.CharField(  # noqa: DJ001 -- unset is NULL (ADR 0040); a CHECK rejects ""
        max_length=255, null=True, blank=True
    )

    # The phone provider's portal (CRM call ingestion). `phone_provider_enabled`
    # is the one switch for the integration; the tasks read the four login
    # values at the point of use and fail there, naming what is missing.
    phone_provider_enabled = models.BooleanField(default=False)
    phone_provider_recording_deletion_enabled = models.BooleanField(default=False)
    phone_provider_base_url = models.URLField(null=True, blank=True, default=None)  # noqa: DJ001 -- unset is NULL (ADR 0040)
    phone_provider_username = models.TextField(blank=True, null=True)  # noqa: DJ001 -- unset is NULL (ADR 0040)
    phone_provider_password = models.TextField(blank=True, null=True)  # noqa: DJ001 -- unset is NULL (ADR 0040)
    phone_provider_account_code = models.CharField(  # noqa: DJ001 -- unset is NULL (ADR 0040)
        max_length=100, blank=True, null=True
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        # Fable: pinned to the table v1 created for the phone-provider row.
        # v1's dump restores by table name, and the scrubber's private-table
        # list names this one, so keeping it moves no data and changes no
        # scrub contract. The physical rename belongs to the post-cutover
        # "purge v1/v2 names" sweep in docs/rewrite-status.md.
        db_table = "crm_phoneprovidersettings"
        verbose_name = "Integration Settings"
        verbose_name_plural = "Integration Settings"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.CheckConstraint(
                condition=models.Q(id=1),
                name="core_integrationsettings_singleton",
            ),
            models.CheckConstraint(
                condition=~models.Q(google_maps_api_key=""),
                name="core_integrationsettings_google_maps_api_key_not_blank",
            ),
            models.CheckConstraint(
                condition=~models.Q(phone_provider_base_url=""),
                name="core_integrationsettings_phone_provider_base_url_not_blank",
            ),
            models.CheckConstraint(
                condition=~models.Q(phone_provider_username=""),
                name="core_integrationsettings_phone_provider_username_not_blank",
            ),
            models.CheckConstraint(
                condition=~models.Q(phone_provider_password=""),
                name="core_integrationsettings_phone_provider_password_not_blank",
            ),
            models.CheckConstraint(
                condition=~models.Q(phone_provider_account_code=""),
                name="core_integrationsettings_phone_provider_account_code_not_blank",
            ),
        ]

    def __str__(self) -> str:
        return "integration settings"

    @classmethod
    def get_solo(cls) -> "IntegrationSettings":
        """Return the singleton. Never creates one — reads do not write.

        Fable: the row is created by core/0003 on a fresh install and by
        `manage.py load_integration_settings` after a scrubbed restore (which
        truncates the table while django_migrations already records 0003).
        Its absence is an operator problem, said plainly rather than papered
        over with a row nobody configured (ADR 0015).
        """
        instance = cls.objects.first()
        if instance is None:
            raise ImproperlyConfigured(
                "IntegrationSettings has no row. A fresh install gets it from "
                "core/0003_integration_settings_row; after a scrubbed restore run "
                "`manage.py load_integration_settings <fixture>` or re-insert the saved row."
            )
        return instance


class _WageBearingStaff(Protocol):
    """Structural view of accounts.Staff used by the wage-rate recompute.

    core cannot import accounts (layer contract), so the recompute goes through
    the app registry and this protocol carries the typing contract.
    """

    base_wage_rate: Decimal
    wage_rate: Decimal

    def save(self, *, update_fields: Iterable[str] | None = None) -> None: ...


def loaded_wage_rate(base_wage_rate: Decimal, loading_percent: Decimal) -> Decimal:
    """Return the costing wage rate a base rate carries at this labour-cost loading.

    The one home for this arithmetic. accounts.Staff._compute_wage_rate, the
    recompute below and the Xero employee checksum all need it, and the first
    two had already drifted — one normalised through ``str``, the other did not.

    ROUND_HALF_UP rather than Decimal's default ROUND_HALF_EVEN: the result
    lands in a ``numeric(_, 2)`` column and Postgres rounds halves away from
    zero, so banker's rounding would disagree with the database at exactly .xx5
    and store a rate the caller cannot reproduce.
    """
    if not base_wage_rate:
        return Decimal("0")
    multiplier = Decimal("1") + loading_percent / Decimal("100")
    return (Decimal(str(base_wage_rate)) * multiplier).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


class CompanyDefaults(SingletonModel):
    """Singleton company configuration managed by django-solo.

    ``get_solo()`` is overridden to READ ONLY. django-solo's implementation is
    ``get_or_create``, and roughly a dozen services call it — several of them
    reached from GET report endpoints, so a plain read of a report would create
    a row. A GET is a safe method; it does not write. That the create happened
    to fail here on ``shop_company`` (NOT NULL, no default) made it visible;
    it would have been just as wrong silently succeeding.
    """

    @classmethod
    def get_solo(cls) -> "CompanyDefaults":
        """Return the singleton. Never creates one — reads do not write.

        The row comes from the v1 data restore. Its absence means the install
        was never seeded, which is an operator action, so this says so rather
        than fabricating a configuration nobody chose (ADR 0015, ADR 0038).
        """
        instance = cls.objects.first()
        if instance is None:
            raise ImproperlyConfigured(
                "CompanyDefaults has no row. It comes from the v1 data restore; "
                "on a fresh install create it with a shop_company set."
            )
        return instance

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
    # KAN-351: An indicative starting point, never a measurement. The components
    # are annual leave (~8%), public holidays (~6%), sick leave (~4%),
    # bereavement leave and employer-paid ACC (~2%), ESCT at 0% — but the total
    # is per-business and measurable, as booked paid non-worked hours over
    # worked hours. MSM's own data puts it near 23%. Setting this to the
    # annual-leave component alone is what mispriced ~19k cost lines.
    labour_cost_loading = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=20.00,
        help_text=(
            "Percentage added to each base wage to recover paid non-worked time in "
            "the labour cost assigned to worked hours. Include annual leave, public "
            "holidays, sick leave, bereavement leave, and employer-paid ACC time; "
            "measure the percentage for this business (20.00 turns $40.00 into $48.00)."
        ),
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
    session_replay_enabled = models.BooleanField(
        default=True,
        help_text=(
            "Record staff browser sessions for diagnostics. Recordings capture "
            "everything on screen and are visible to superusers only."
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

    # What Google knows about the address above, filled when an operator picks a
    # candidate on the settings screen and refreshed only when they pick again.
    # Column names follow SupplierPickupAddress, which stores the same facts for
    # supplier addresses: one vocabulary, not two.
    #
    # The holidays subdivision is NOT stored. It is a pure function of `region`
    # (apps.core.geocoding.nz_subdivision_for_region), and
    # the mapping belongs to the holidays package — freezing it in a column
    # would keep answering with last year's table after an upgrade renamed a
    # code or added an alias.
    formatted_address = models.CharField(  # noqa: DJ001 -- unset is NULL (ADR 0040); never geocoded
        max_length=500,
        null=True,
        blank=True,
        verbose_name="Address as Google has it",
        help_text=(
            "The address Google matched, filled in when someone picks a candidate on this "
            "screen. Read-only: it records what was confirmed, not what was typed."
        ),
    )
    region = models.CharField(  # noqa: DJ001 -- unset is NULL (ADR 0040); never geocoded
        max_length=100,
        null=True,
        blank=True,
        verbose_name="Region",
        help_text=(
            "The region Google reports for the address above — 'Canterbury Region', or "
            "plainly 'Auckland'. Read-only, and the basis for which public holidays this "
            "business observes."
        ),
    )
    google_place_id = models.CharField(  # noqa: DJ001 -- unset is NULL (ADR 0040)
        max_length=255, null=True, blank=True
    )
    latitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    longitude = models.DecimalField(max_digits=10, decimal_places=7, null=True, blank=True)
    address_raw_json = models.JSONField(
        null=True,
        blank=True,
        help_text="Raw JSON data from Google Places for the address above",
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

    shop_company = models.ForeignKey(
        "company.Company",
        on_delete=models.PROTECT,
        related_name="+",
        help_text="Internal company used for tracking shop work.",
    )

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
            models.CheckConstraint(
                condition=~models.Q(address_line1=""), name="address_line1_not_blank"
            ),
            models.CheckConstraint(
                condition=~models.Q(address_line2=""), name="address_line2_not_blank"
            ),
            models.CheckConstraint(condition=~models.Q(city=""), name="city_not_blank"),
            models.CheckConstraint(
                condition=~models.Q(company_acronym=""), name="company_acronym_not_blank"
            ),
            models.CheckConstraint(
                condition=~models.Q(company_email=""), name="company_email_not_blank"
            ),
            models.CheckConstraint(
                condition=~models.Q(company_url=""), name="company_url_not_blank"
            ),
            models.CheckConstraint(
                condition=~models.Q(gdrive_how_we_work_folder_id=""),
                name="gdrive_how_we_work_folder_id_not_blank",
            ),
            models.CheckConstraint(
                condition=~models.Q(gdrive_quotes_folder_id=""),
                name="gdrive_quotes_folder_id_not_blank",
            ),
            models.CheckConstraint(
                condition=~models.Q(gdrive_quotes_folder_url=""),
                name="gdrive_quotes_folder_url_not_blank",
            ),
            models.CheckConstraint(
                condition=~models.Q(gdrive_reference_library_folder_id=""),
                name="gdrive_reference_library_folder_id_not_blank",
            ),
            models.CheckConstraint(
                condition=~models.Q(gdrive_sops_folder_id=""),
                name="gdrive_sops_folder_id_not_blank",
            ),
            models.CheckConstraint(
                condition=~models.Q(google_shared_drive_id=""),
                name="google_shared_drive_id_not_blank",
            ),
            models.CheckConstraint(
                condition=~models.Q(master_quote_template_id=""),
                name="master_quote_template_id_not_blank",
            ),
            models.CheckConstraint(
                condition=~models.Q(master_quote_template_url=""),
                name="master_quote_template_url_not_blank",
            ),
            models.CheckConstraint(
                condition=~models.Q(formatted_address=""), name="formatted_address_not_blank"
            ),
            models.CheckConstraint(
                condition=~models.Q(google_place_id=""),
                name="companydefaults_google_place_id_not_blank",
            ),
            models.CheckConstraint(condition=~models.Q(post_code=""), name="post_code_not_blank"),
            models.CheckConstraint(condition=~models.Q(region=""), name="region_not_blank"),
            models.CheckConstraint(
                condition=~models.Q(suburb=""),
                name="workflow_companydefaults_suburb_not_blank",
            ),
            models.CheckConstraint(
                condition=~models.Q(test_company_name=""), name="test_company_name_not_blank"
            ),
            models.CheckConstraint(
                condition=~models.Q(xero_shortcode=""), name="xero_shortcode_not_blank"
            ),
            models.CheckConstraint(
                condition=~models.Q(xero_tenant_id=""),
                name="workflow_companydefaults_xero_tenant_id_not_blank",
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
        """Save the singleton, recomputing staff wage rates if the loading changed."""
        # ``update_fields`` is the caller's write intent, not merely a SQL
        # optimisation. A long-running Xero sync holds this singleton in memory
        # and later saves only its cursor timestamps; comparing an excluded
        # loading against the current row mistakes a stale instance for a
        # loading edit and recomputes every Staff rate from the stale value.
        #
        # Materialised before the membership test: the parameter is an
        # ``Iterable[str]`` and Django only freezes it inside ``Model.save``, so
        # asking a generator whether it contains the loading would consume it and
        # leave super().save() an empty update — a silent no-op write.
        if update_fields is not None:
            update_fields = frozenset(update_fields)
        writes_loading = update_fields is None or "labour_cost_loading" in update_fields

        loading_changed = False
        if writes_loading and self.pk:
            try:
                old = CompanyDefaults.objects.get(pk=self.pk)
                loading_changed = old.labour_cost_loading != self.labour_cost_loading
            # deliberate-swallow: no prior row means no prior loading to compare
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
        """Bulk-recompute staff wage rates from the current labour-cost loading."""
        # App-registry lookup instead of `from apps.accounts.models import Staff`:
        # core sits below accounts in the layer contract, so even a function-level
        # import is off-limits. The cast to the protocol carries the field typing.
        staff_model = django_apps.get_model("accounts", "Staff")
        staff_rows = cast(
            "Iterable[_WageBearingStaff]",
            staff_model._default_manager.filter(base_wage_rate__gt=0),
        )
        for staff in staff_rows:
            staff.wage_rate = loaded_wage_rate(staff.base_wage_rate, self.labour_cost_loading)
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
        """Save the row, generating the API key on first save."""
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
