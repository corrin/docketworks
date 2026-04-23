from decimal import Decimal

from django.db import models
from solo.models import SingletonModel


class CompanyDefaults(SingletonModel):
    company_name = models.CharField(max_length=255)
    company_acronym = models.CharField(
        max_length=10,
        null=True,
        blank=True,
        help_text="Short acronym for the company (e.g., 'MSM' for Morris Sheetmetal)",
    )
    time_markup = models.DecimalField(max_digits=5, decimal_places=2, default=0.3)
    materials_markup = models.DecimalField(max_digits=5, decimal_places=2, default=0.2)
    charge_out_rate = models.DecimalField(
        max_digits=6, decimal_places=2, default=105.00
    )  # rate per hour
    wage_rate = models.DecimalField(
        max_digits=6, decimal_places=2, default=32.00
    )  # rate per hour
    annual_leave_loading = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=8.00,
        help_text="Percentage added to base_wage_rate to get costing wage_rate (8.00 = 8%)",
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
    master_quote_template_url = models.URLField(
        null=True,
        blank=True,
        help_text="URL to the master Google Sheets quote template",
    )

    master_quote_template_id = models.CharField(
        null=True,
        blank=True,
        help_text="Google Sheets ID for the quote template",
        max_length=100,
    )

    gdrive_quotes_folder_url = models.URLField(
        null=True,
        blank=True,
        help_text="URL to the Google Drive folder for storing quotes",
    )

    gdrive_quotes_folder_id = models.CharField(
        null=True,
        blank=True,
        help_text="Google Drive folder ID for storing quotes",
        max_length=100,
    )

    # Google Shared Drive — Operations Manual folder hierarchy
    google_shared_drive_id = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        help_text="Google Shared Drive ID for the company shared drive",
    )
    gdrive_how_we_work_folder_id = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        help_text="Folder ID for '01 - How we work' (policies, basics)",
    )
    gdrive_sops_folder_id = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        help_text="Folder ID for '02 - SOPs' (standard operating procedures)",
    )
    gdrive_reference_library_folder_id = models.CharField(
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
    xero_tenant_id = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        help_text="The Xero tenant ID to use for this company",
    )
    xero_shortcode = models.CharField(
        max_length=20,
        null=True,
        blank=True,
        help_text="Xero organisation shortcode for deep linking (e.g., '!8-5Xl')",
    )
    enable_xero_sync = models.BooleanField(
        default=True,
        help_text="Gate for Xero sync. Defaults True (prod). Dev fixture sets False; seed_xero_from_database sets True after prod IDs are cleared.",
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
        help_text="Show Saturday and Sunday in timesheet views (7-day week). Off = 5-day Mon-Fri.",
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
    address_line1 = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text="Street address line 1",
    )
    address_line2 = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text="Street address line 2 (optional)",
    )
    suburb = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        help_text="Suburb (for NZ addresses)",
    )
    city = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        help_text="City",
    )
    post_code = models.CharField(
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
    company_email = models.EmailField(
        null=True,
        blank=True,
        help_text="Company contact email address",
    )
    company_phone = models.CharField(
        max_length=30,
        null=True,
        blank=True,
        help_text="Company phone number",
    )
    company_url = models.URLField(
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

    # Shop client configuration
    shop_client_name = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text="Name of the internal shop client for tracking shop work (e.g., 'MSM (Shop)')",
    )

    # Test client configuration
    test_client_name = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text="Name of the test client used for testing (e.g., 'ABC Carpet Cleaning TEST IGNORE'). This client's name is preserved during data backports.",
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

    class Meta:
        verbose_name = "Company Defaults"
        verbose_name_plural = "Company Defaults"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(id=1),
                name="companydefaults_singleton",
            ),
        ]

    def save(self, *args, **kwargs):
        # Check if annual_leave_loading changed - if so, recompute all staff wage_rates
        loading_changed = False
        if self.pk:
            try:
                old = CompanyDefaults.objects.get(pk=self.pk)
                loading_changed = old.annual_leave_loading != self.annual_leave_loading
            except CompanyDefaults.DoesNotExist:
                pass

        result = super().save(*args, **kwargs)

        if loading_changed:
            self._recompute_all_staff_wage_rates()

        return result

    def _recompute_all_staff_wage_rates(self):
        """Bulk-recompute wage_rate for all staff based on current annual_leave_loading."""
        from apps.accounts.models import Staff

        loading_multiplier = Decimal("1") + self.annual_leave_loading / Decimal("100")
        for staff in Staff.objects.filter(base_wage_rate__gt=0):
            staff.wage_rate = (staff.base_wage_rate * loading_multiplier).quantize(
                Decimal("0.01")
            )
            staff.save(update_fields=["wage_rate", "updated_at"])

    @property
    def llm_api_key(self):
        """
        Returns the API key of the active LLM provider.
        """
        from .ai_provider import AIProvider

        active_provider = AIProvider.objects.filter(default=True).first()
        return active_provider.api_key if active_provider else None

    def __str__(self):
        return self.company_name
