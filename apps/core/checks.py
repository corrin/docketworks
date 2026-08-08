"""Django system checks for core-owned configuration contracts."""

from collections.abc import Sequence
from typing import Any

from django.apps import AppConfig
from django.core.checks import Error, register

from apps.core.models import CompanyDefaults
from apps.core.settings_metadata import (
    INTERNAL_SECTION,
    SettingsMetadataError,
    get_registered_section,
    get_ui_type_for_field,
    iter_company_defaults_fields,
)


@register()
def check_company_defaults_field_sections(
    app_configs: Sequence[AppConfig] | None,
    # Django's check registry owns these framework-specific keyword values;
    # this boundary never reads or passes them into application code.
    **_kwargs: Any,
) -> list[Error]:
    """Report every model field the settings registry cannot render safely."""
    if app_configs is not None and all(app_config.label != "core" for app_config in app_configs):
        return []

    errors: list[Error] = []
    for field in iter_company_defaults_fields():
        try:
            section_key = get_registered_section(field)
            if section_key != INTERNAL_SECTION:
                get_ui_type_for_field(field)
        except SettingsMetadataError as exc:  # deliberate-swallow: each exception is converted
            # into a Django Error; continuing reports every invalid field in one boot check.
            errors.append(
                Error(
                    str(exc),
                    hint=exc.hint,
                    obj=CompanyDefaults,
                    id=exc.check_id,
                )
            )
            continue
    return errors
