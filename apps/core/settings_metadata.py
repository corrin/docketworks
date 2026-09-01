"""Typed metadata for the dynamic company-defaults settings screen.

The model is the source of field labels, requiredness and help text; this module
adds only presentation facts the model cannot express: section placement and
the frontend widget required for each Django field class.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Literal

from django.core.exceptions import ImproperlyConfigured
from django.db import models

from apps.core.models import CompanyDefaults
from apps.core.schemas import ResponseSchema

type SettingsSectionKey = Literal["company", "working_hours", "finances", "kpi", "setup", "xero"]
type RegistrySectionKey = SettingsSectionKey | Literal["internal"]
type SettingsFieldType = Literal[
    "image",
    "email",
    "url",
    "text",
    "textarea",
    "number",
    "boolean",
    "time",
    "datetime",
    "date",
    "company",
    "xero_branding_theme",
]
type SettingsCheckId = Literal["core.E001", "core.E002", "core.E003"]

# Django model reflection returns heterogeneous Field specialisations. The
# concrete class is validated before any type-specific metadata is read, so
# object is confined to this dynamic boundary rather than leaking downstream.
type ModelField = models.Field[object, object]
type FieldTypeRule = tuple[type[ModelField], SettingsFieldType]


@dataclass(frozen=True, slots=True)
class SettingsSectionDefinition:
    """Display identity and order for one public settings section."""

    key: SettingsSectionKey
    title: str
    order: int


SETTINGS_SECTIONS: tuple[SettingsSectionDefinition, ...] = (
    SettingsSectionDefinition("company", "Company", 1),
    SettingsSectionDefinition("working_hours", "Working Hours", 2),
    SettingsSectionDefinition("finances", "Finances", 3),
    SettingsSectionDefinition("kpi", "KPI & Thresholds", 4),
    SettingsSectionDefinition("setup", "Setup", 5),
    SettingsSectionDefinition("xero", "Xero", 6),
)

INTERNAL_SECTION: Literal["internal"] = "internal"

SETTINGS_SECTION_BY_KEY: dict[SettingsSectionKey, SettingsSectionDefinition] = {
    section.key: section for section in SETTINGS_SECTIONS
}

# More-specific subclasses precede their parents because isinstance returns the
# first matching rule. DateTimeField before DateField fixes v1's date-only
# timestamp widgets; representing these as rules rather than a lookup dict makes
# the ordered dispatch semantics explicit.
FIELD_TYPE_RULES: tuple[FieldTypeRule, ...] = (
    (models.ImageField, "image"),
    (models.EmailField, "email"),
    (models.URLField, "url"),
    (models.CharField, "text"),
    (models.TextField, "textarea"),
    (models.IntegerField, "number"),
    (models.DecimalField, "number"),
    (models.FloatField, "number"),
    (models.BooleanField, "boolean"),
    (models.TimeField, "time"),
    (models.DateTimeField, "datetime"),
    (models.DateField, "date"),
    (models.UUIDField, "text"),
)

# Renaming is excluded from this form because company_name is the identity the
# settings screen is organised around; dedicated identity workflows may still
# change it elsewhere.
COMPANY_DEFAULTS_READ_ONLY_FIELDS: frozenset[str] = frozenset(
    # company_name is the identity the screen is organised around; the other
    # two are Google's answer about the address, not a preference to set.
    {"company_name", "formatted_address", "region"}
)

# There is deliberately no CRM section. Its only fields moved to the
# IntegrationSettings singleton (ADR 0053: credentials never sit on the
# any-staff CompanyDefaults), and retaining the section made the screen offer
# a button that opened an empty form.
COMPANY_DEFAULTS_FIELD_SECTIONS: dict[str, RegistrySectionKey] = {
    "company_name": "company",
    "company_acronym": "company",
    "address_line1": "company",
    "address_line2": "company",
    "suburb": "company",
    "city": "company",
    "post_code": "company",
    "country": "company",
    # Derived from the address by Google, shown read-only so nobody types a
    # region the holiday calendar then disagrees with.
    "formatted_address": "company",
    "region": "company",
    # The same lookup's machine detail: no operator sets or reads these.
    "google_place_id": "internal",
    "latitude": "internal",
    "longitude": "internal",
    "address_raw_json": "internal",
    "company_email": "company",
    "company_url": "company",
    "logo": "company",
    "logo_wide": "company",
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
    "workshop_efficiency_factor": "working_hours",
    "time_markup": "finances",
    "materials_markup": "finances",
    "gst_rate": "finances",
    "wage_rate": "finances",
    "labour_cost_loading": "finances",
    "financial_year_start_month": "finances",
    "kpi_daily_billable_hours_green": "kpi",
    "kpi_daily_billable_hours_amber": "kpi",
    "kpi_daily_gp_target": "kpi",
    "kpi_daily_shop_hours_percentage": "kpi",
    "kpi_job_gp_target_percentage": "kpi",
    "kpi_daily_gp_green": "kpi",
    "kpi_daily_gp_amber": "kpi",
    "daily_approved_hours_target": "kpi",
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
    "shop_company": "setup",
    "test_company_name": "setup",
    "job_delta_soft_fail": "setup",
    "accounting_provider": "xero",
    "xero_tenant_id": "xero",
    "xero_shortcode": "xero",
    "xero_sales_branding_theme_id": "xero",
    "xero_quote_terms": "xero",
    "enable_xero_sync": "xero",
    "xero_automated_day_floor": "xero",
    "xero_payroll_calendar_name": "xero",
    "xero_payroll_calendar_id": "xero",
    "xero_payroll_start_date": "xero",
    "last_xero_sync": "xero",
    "last_xero_deep_sync": "xero",
    "id": "internal",
    "created_at": "internal",
    "updated_at": "internal",
}


class SettingsFieldOut(ResponseSchema):
    """One settings field as the screen renders it."""

    key: str
    label: str
    type: SettingsFieldType
    required: bool
    help_text: str
    section: SettingsSectionKey
    read_only: bool


class SettingsSectionOut(ResponseSchema):
    """One settings section with its fields."""

    key: SettingsSectionKey
    title: str
    order: int
    fields: list[SettingsFieldOut]


class CompanyDefaultsSchemaOut(ResponseSchema):
    """Every non-empty settings section in display order."""

    sections: list[SettingsSectionOut]


class SettingsMetadataError(ImproperlyConfigured):
    """A registry defect that prevents the settings form being rendered safely."""

    def __init__(self, message: str, *, check_id: SettingsCheckId, hint: str) -> None:
        """Carry the same diagnosis to Django checks and runtime error handling."""
        super().__init__(message)
        self.check_id = check_id
        self.hint = hint


def iter_company_defaults_fields() -> Iterator[ModelField]:
    """Yield every concrete field the settings registry must classify."""
    for field in CompanyDefaults._meta.get_fields():
        if not isinstance(field, models.Field):
            continue
        yield field


def get_registered_section(field: ModelField) -> RegistrySectionKey:
    """Return a field's registered section or raise its boot-check failure."""
    section_key = COMPANY_DEFAULTS_FIELD_SECTIONS.get(field.name)
    if section_key is None:
        raise SettingsMetadataError(
            f"CompanyDefaults field '{field.name}' has no section defined",
            check_id="core.E001",
            hint=(
                f"Add '{field.name}' to COMPANY_DEFAULTS_FIELD_SECTIONS in "
                "apps/core/settings_metadata.py"
            ),
        )
    if section_key != INTERNAL_SECTION and section_key not in SETTINGS_SECTION_BY_KEY:
        valid_sections = sorted([*SETTINGS_SECTION_BY_KEY, INTERNAL_SECTION])
        raise SettingsMetadataError(
            f"CompanyDefaults field '{field.name}' is mapped to unknown section '{section_key}'",
            check_id="core.E002",
            hint=f"Valid sections: {', '.join(valid_sections)}",
        )
    return section_key


def get_ui_type_for_field(field: ModelField) -> SettingsFieldType:
    """Return the supported frontend widget for a concrete model field."""
    if field.name == "xero_sales_branding_theme_id":
        return "xero_branding_theme"

    if isinstance(field, models.ForeignKey):
        remote = field.remote_field
        if remote is not None and remote.model._meta.label == "company.Company":
            return "company"
        related_label = "unresolved" if remote is None else remote.model._meta.label
        raise SettingsMetadataError(
            f"No UI type mapping for ForeignKey to {related_label}",
            check_id="core.E003",
            hint="Add an explicit frontend widget before registering this foreign key.",
        )

    for field_class, ui_type in FIELD_TYPE_RULES:
        if isinstance(field, field_class):
            return ui_type
    raise SettingsMetadataError(
        f"No UI type mapping for {type(field).__name__}",
        check_id="core.E003",
        hint="Add the field class and its supported widget to FIELD_TYPE_RULES.",
    )


def _field_metadata(field: ModelField, section: SettingsSectionKey) -> SettingsFieldOut:
    """Build the wire metadata for one validated public field."""
    return SettingsFieldOut(
        key=field.name,
        label=str(field.verbose_name).title(),
        type=get_ui_type_for_field(field),
        required=not field.blank and not field.null,
        help_text=str(field.help_text) if field.help_text else "",
        section=section,
        read_only=field.name in COMPANY_DEFAULTS_READ_ONLY_FIELDS,
    )


def build_company_defaults_schema() -> CompanyDefaultsSchemaOut:
    """Build the complete settings-screen contract from the live model."""
    fields_by_section: dict[SettingsSectionKey, list[SettingsFieldOut]] = {
        section.key: [] for section in SETTINGS_SECTIONS
    }
    for field in iter_company_defaults_fields():
        section_key = get_registered_section(field)
        if section_key == INTERNAL_SECTION:
            continue
        fields_by_section[section_key].append(_field_metadata(field, section_key))

    return CompanyDefaultsSchemaOut(
        sections=[
            SettingsSectionOut(
                key=definition.key,
                title=definition.title,
                order=definition.order,
                fields=fields_by_section[definition.key],
            )
            for definition in SETTINGS_SECTIONS
            if fields_by_section[definition.key]
        ]
    )
