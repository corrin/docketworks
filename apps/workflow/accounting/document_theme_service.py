"""Selection and persistence of the sales document branding theme."""

from uuid import UUID

from apps.workflow.accounting.provider import AccountingProvider
from apps.workflow.accounting.types import DocumentTheme
from apps.workflow.models.company_defaults import CompanyDefaults


def resolve_and_persist_sales_branding_theme(
    provider: AccountingProvider,
    company_defaults: CompanyDefaults,
) -> DocumentTheme | None:
    """Preserve a live selection or persist the provider's first theme.

    Providers return themes in their preferred order. The Xero provider orders
    them by Xero's ``SortOrder``, so its first item is the valid unattended
    starting point for an installation that has not selected a theme yet.
    """
    themes = provider.list_document_themes()
    if not themes:
        return None

    configured_id = company_defaults.xero_sales_branding_theme_id
    selected_theme = next(
        (
            theme
            for theme in themes
            if configured_id is not None and theme.external_id == str(configured_id)
        ),
        themes[0],
    )
    selected_id = UUID(selected_theme.external_id)

    if configured_id == selected_id:
        return selected_theme

    updated = CompanyDefaults.objects.filter(
        pk=company_defaults.pk,
        xero_sales_branding_theme_id=configured_id,
    ).update(xero_sales_branding_theme_id=selected_id)
    CompanyDefaults.clear_cache()

    if updated == 1:
        company_defaults.xero_sales_branding_theme_id = selected_id
        return selected_theme

    current_id = CompanyDefaults.objects.values_list(
        "xero_sales_branding_theme_id", flat=True
    ).get(pk=company_defaults.pk)
    current_theme = next(
        (
            theme
            for theme in themes
            if current_id is not None and theme.external_id == str(current_id)
        ),
        None,
    )
    if current_theme is None:
        raise ValueError(
            "The Xero sales branding theme changed while it was being configured."
        )

    company_defaults.xero_sales_branding_theme_id = current_id
    return current_theme
