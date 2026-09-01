"""Regression tests for the metadata that drives the company settings screen."""

import pytest
from django.db import models
from django.test import Client

from apps.core import settings_metadata
from apps.core.checks import check_company_defaults_field_sections
from apps.core.models import CompanyDefaults
from apps.core.settings_metadata import (
    COMPANY_DEFAULTS_FIELD_SECTIONS,
    FIELD_TYPE_RULES,
    CompanyDefaultsSchemaOut,
    SettingsFieldType,
    SettingsMetadataError,
    SettingsSectionKey,
    SettingsSectionOut,
    build_company_defaults_schema,
    get_ui_type_for_field,
)

URL = "/api/company-defaults/schema/"

SECTION_KEYS_IN_ORDER: list[SettingsSectionKey] = [
    "company",
    "working_hours",
    "finances",
    "kpi",
    "setup",
    "xero",
]


def _schema(api: Client) -> CompanyDefaultsSchemaOut:
    response = api.get(URL)
    assert response.status_code == 200, response.content
    return CompanyDefaultsSchemaOut.model_validate(response.json())


def _section(schema: CompanyDefaultsSchemaOut, key: SettingsSectionKey) -> SettingsSectionOut:
    return next(section for section in schema.sections if section.key == key)


@pytest.mark.django_db
def test_requires_authentication(client: Client) -> None:
    """A route refactor could omit auth; an anonymous settings-schema read must remain rejected."""
    assert client.get(URL).status_code == 401


@pytest.mark.django_db
def test_sections_match_the_registry_exactly(api: Client) -> None:
    """Adding an empty section would create a dead settings button, as v1's CRM entry did."""
    keys = [section.key for section in _schema(api).sections]

    assert keys == SECTION_KEYS_IN_ORDER


@pytest.mark.django_db
def test_every_concrete_field_reaches_the_screen_except_internal(api: Client) -> None:
    """A model field omitted from the registry would silently disappear from the settings screen."""
    schema = _schema(api)
    served = {field.key for section in schema.sections for field in section.fields}
    internal = {
        field_name
        for field_name, section in COMPANY_DEFAULTS_FIELD_SECTIONS.items()
        if section == "internal"
    }

    assert served == set(COMPANY_DEFAULTS_FIELD_SECTIONS) - internal


@pytest.mark.django_db
def test_company_name_is_read_only(api: Client) -> None:
    """A metadata edit could expose identity renaming through the general company form."""
    by_key = {field.key: field for field in _section(_schema(api), "company").fields}

    assert by_key["company_name"].read_only is True
    assert by_key["company_name"].required is True
    assert by_key["company_acronym"].read_only is False


@pytest.mark.django_db
def test_labour_cost_loading_names_and_explains_the_whole_cost(api: Client) -> None:
    """An operator must not mistake the setting for annual leave alone again."""
    by_key = {field.key: field for field in _section(_schema(api), "finances").fields}

    loading = by_key["labour_cost_loading"]
    assert loading.label == "Labour Cost Loading"
    assert "paid non-worked time" in loading.help_text
    assert "annual leave, public holidays, sick leave, bereavement leave" in loading.help_text
    assert "$40.00 into $48.00" in loading.help_text


@pytest.mark.django_db
def test_branding_theme_gets_its_picker_widget(api: Client) -> None:
    """Class-only dispatch would render the Xero theme UUID as text instead of its remote picker."""
    by_key = {field.key: field for field in _section(_schema(api), "xero").fields}

    theme = by_key["xero_sales_branding_theme_id"]
    assert theme.type == "xero_branding_theme"
    assert theme.label == "Xero Sales Branding Theme"
    assert theme.required is False
    assert "layout and presentation" in theme.help_text

    assert by_key["xero_quote_terms"].type == "textarea"
    assert by_key["xero_quote_terms"].label == "Xero Quote Terms"


@pytest.mark.parametrize(
    ("field_name", "ui_type"),
    [
        ("company_name", "text"),
        ("company_email", "email"),
        ("company_url", "url"),
        ("logo", "image"),
        ("logo_wide", "image"),
        ("mon_start", "time"),
        ("xero_payroll_start_date", "date"),
        ("last_xero_sync", "datetime"),
        ("gst_rate", "number"),
        ("xero_automated_day_floor", "number"),
        ("enable_xero_sync", "boolean"),
        ("xero_quote_terms", "textarea"),
        ("xero_payroll_calendar_id", "text"),
        ("shop_company", "company"),
        ("xero_sales_branding_theme_id", "xero_branding_theme"),
    ],
)
def test_ui_type_follows_the_live_field_contract(
    field_name: str, ui_type: SettingsFieldType
) -> None:
    """Reordering subclass rules could collapse URLs or timestamps into their parent widgets."""
    field = CompanyDefaults._meta.get_field(field_name)
    assert isinstance(field, models.Field)

    assert get_ui_type_for_field(field) == ui_type


def test_unmapped_field_class_fails_loudly() -> None:
    """A new Django field class must not silently degrade to a text input it may not support."""
    with pytest.raises(SettingsMetadataError) as error:
        get_ui_type_for_field(models.BinaryField())

    assert error.value.check_id == "core.E003"
    assert "BinaryField" in str(error.value)


def test_foreign_key_without_a_dedicated_widget_fails_loudly() -> None:
    """A future relation must ship its selector rather than becoming an opaque ID text box."""
    field = models.ForeignKey(CompanyDefaults, on_delete=models.CASCADE)

    with pytest.raises(SettingsMetadataError) as error:
        get_ui_type_for_field(field)

    assert error.value.check_id == "core.E003"
    assert "core.CompanyDefaults" in str(error.value)


def test_schema_builder_rejects_an_unregistered_field(monkeypatch: pytest.MonkeyPatch) -> None:
    """A deployment that skipped system checks must still fail instead of serving a partial form."""
    mapping = {
        field_name: section
        for field_name, section in COMPANY_DEFAULTS_FIELD_SECTIONS.items()
        if field_name != "wage_rate"
    }
    monkeypatch.setattr(settings_metadata, "COMPANY_DEFAULTS_FIELD_SECTIONS", mapping)

    with pytest.raises(SettingsMetadataError) as error:
        build_company_defaults_schema()

    assert error.value.check_id == "core.E001"
    assert "wage_rate" in str(error.value)


def test_check_passes_on_the_live_registry() -> None:
    """Registry drift from the live model must be caught before a release reaches the endpoint."""
    assert check_company_defaults_field_sections(None) == []


def test_check_fails_on_a_field_without_a_section(monkeypatch: pytest.MonkeyPatch) -> None:
    """Adding a model field without classifying it must produce the actionable E001 boot error."""
    mapping = {
        field_name: section
        for field_name, section in COMPANY_DEFAULTS_FIELD_SECTIONS.items()
        if field_name != "wage_rate"
    }
    monkeypatch.setattr(settings_metadata, "COMPANY_DEFAULTS_FIELD_SECTIONS", mapping)

    errors = check_company_defaults_field_sections(None)

    assert [error.id for error in errors] == ["core.E001"]
    assert "wage_rate" in errors[0].msg


def test_check_fails_on_an_unknown_section(monkeypatch: pytest.MonkeyPatch) -> None:
    """A plausible singular/plural typo in a section name must fail boot as E002."""
    mapping = dict(COMPANY_DEFAULTS_FIELD_SECTIONS, wage_rate="finance")
    monkeypatch.setattr(settings_metadata, "COMPANY_DEFAULTS_FIELD_SECTIONS", mapping)

    errors = check_company_defaults_field_sections(None)

    assert [error.id for error in errors] == ["core.E002"]
    assert "wage_rate" in errors[0].msg


def test_check_fails_on_an_unmapped_field_class(monkeypatch: pytest.MonkeyPatch) -> None:
    """Removing a supported widget rule must identify every affected live field as E003."""
    rules = tuple(
        (field_class, ui_type)
        for field_class, ui_type in FIELD_TYPE_RULES
        if field_class is not models.TimeField
    )
    monkeypatch.setattr(settings_metadata, "FIELD_TYPE_RULES", rules)

    errors = check_company_defaults_field_sections(None)

    assert {error.id for error in errors} == {"core.E003"}
    assert "TimeField" in errors[0].msg
