"""
Settings field metadata for dynamic UI generation.

This module provides:
1. SettingsSection - enum-like class defining valid sections
2. Field metadata extraction utilities
3. Django-to-UI field type mapping

When adding a new field to CompanyDefaults:
1. Add the field to the model with help_text
2. Add the field name to COMPANY_DEFAULTS_FIELD_SECTIONS below
3. The system check will catch any missing mappings at startup
"""

from typing import Any

from django.db import models


class SettingsSection:
    """
    Registry of valid settings sections with display metadata.

    Each section is a tuple of (key, title, order).
    Order determines display sequence in the UI.
    """

    COMPANY = ("company", "Company", 1)
    WORKING_HOURS = ("working_hours", "Working Hours", 2)
    FINANCES = ("finances", "Finances", 3)
    KPI = ("kpi", "KPI & Thresholds", 4)
    SETUP = ("setup", "Setup", 5)
    XERO = ("xero", "Xero", 6)
    INTERNAL = ("internal", "Internal", 99)  # Hidden from UI

    @classmethod
    def all_sections(cls) -> list[tuple[str, str, int]]:
        """Return all sections as list of (key, title, order) tuples."""
        return [
            v
            for k, v in vars(cls).items()
            if not k.startswith("_") and isinstance(v, tuple) and len(v) == 3
        ]

    @classmethod
    def get_section_info(cls, key: str) -> tuple[str, str, int] | None:
        """Get section info by key."""
        for section in cls.all_sections():
            if section[0] == key:
                return section
        return None


# Mapping from Django field types to UI input types
# Note: Order matters! More specific types (subclasses) must come before their parent classes.
# e.g., URLField and EmailField must come before CharField since they inherit from it.
DJANGO_TO_UI_TYPE: dict[type["models.Field[Any, Any]"], str] = {
    # ImageField before FileField (more specific first)
    models.ImageField: "image",
    # Specific CharField subclasses first
    models.EmailField: "email",
    models.URLField: "url",
    # Then the base CharField
    models.CharField: "text",
    models.TextField: "textarea",
    models.IntegerField: "number",
    models.DecimalField: "number",
    models.FloatField: "number",
    models.BooleanField: "boolean",
    models.TimeField: "time",
    models.DateField: "date",
    models.DateTimeField: "datetime",
}


# Fields that should not be editable via the API (e.g., primary keys)
COMPANY_DEFAULTS_READ_ONLY_FIELDS: set[str] = {"company_name"}

# Field name to section mapping for CompanyDefaults
# This is the authoritative source for which section each field belongs to.
# Adding a field to CompanyDefaults without adding it here will cause a startup error.
COMPANY_DEFAULTS_FIELD_SECTIONS: dict[str, str] = {
    # Company info
    "company_name": "company",
    "company_acronym": "company",
    "address_line1": "company",
    "address_line2": "company",
    "suburb": "company",
    "city": "company",
    "post_code": "company",
    "country": "company",
    "company_email": "company",
    "company_phone": "company",
    "company_url": "company",
    "logo": "company",
    "logo_wide": "company",
    # Working hours
    "mon_start": "working_hours",
    "mon_end": "working_hours",
    "tue_start": "working_hours",
    "tue_end": "working_hours",
    "wed_start": "working_hours",
    "wed_end": "working_hours",
    "thu_start": "working_hours",
    "thu_end": "working_hours",
    "fri_start": "working_hours",
    "fri_end": "working_hours",
    "weekend_timesheets_enabled": "working_hours",
    # Finances
    "time_markup": "finances",
    "materials_markup": "finances",
    "charge_out_rate": "finances",
    "wage_rate": "finances",
    "annual_leave_loading": "finances",
    "financial_year_start_month": "finances",
    # KPI thresholds
    "kpi_daily_billable_hours_green": "kpi",
    "kpi_daily_billable_hours_amber": "kpi",
    "kpi_daily_gp_target": "kpi",
    "kpi_daily_shop_hours_percentage": "kpi",
    "kpi_job_gp_target_percentage": "kpi",
    "kpi_daily_gp_green": "kpi",
    "kpi_daily_gp_amber": "kpi",
    # Setup (initial configuration)
    "master_quote_template_url": "setup",
    "master_quote_template_id": "setup",
    "gdrive_quotes_folder_url": "setup",
    "gdrive_quotes_folder_id": "setup",
    "google_shared_drive_id": "setup",
    "gdrive_how_we_work_folder_id": "setup",
    "gdrive_sops_folder_id": "setup",
    "gdrive_reference_library_folder_id": "setup",
    "starting_job_number": "setup",
    "starting_po_number": "setup",
    "po_prefix": "setup",
    "shop_client_name": "setup",
    "test_client_name": "setup",
    # Xero integration
    "accounting_provider": "xero",
    "xero_tenant_id": "xero",
    "xero_shortcode": "xero",
    "enable_xero_sync": "xero",
    "xero_payroll_calendar_name": "xero",
    "xero_payroll_calendar_id": "xero",
    "xero_payroll_start_date": "xero",
    "last_xero_sync": "xero",
    "last_xero_deep_sync": "xero",
    # Internal - auto-managed fields, not shown in UI
    "id": "internal",
    "created_at": "internal",
    "updated_at": "internal",
}


def get_ui_type_for_field(field: "models.Field[Any, Any]") -> str:
    """
    Determine the UI input type for a Django model field.

    Returns a string like 'text', 'number', 'boolean', etc.
    """
    for field_class, ui_type in DJANGO_TO_UI_TYPE.items():
        if isinstance(field, field_class):
            return ui_type
    return "text"  # Default fallback


def get_field_metadata(
    field: "models.Field[Any, Any]",
    field_name: str,
    read_only_fields: set[str] | None = None,
) -> dict[str, Any]:
    """
    Extract metadata from a Django model field for UI rendering.

    Returns dict with: key, label, type, required, help_text, section, read_only
    """
    section = COMPANY_DEFAULTS_FIELD_SECTIONS.get(field_name, "company")

    # Get label from verbose_name or derive from field name
    if field.verbose_name and field.verbose_name != field_name.replace("_", " "):
        label = str(field.verbose_name).title()
    else:
        label = field_name.replace("_", " ").title()

    return {
        "key": field_name,
        "label": label,
        "type": get_ui_type_for_field(field),
        "required": not field.blank and not field.null,
        "help_text": field.help_text or "",
        "section": section,
        "read_only": field_name in (read_only_fields or set()),
    }
