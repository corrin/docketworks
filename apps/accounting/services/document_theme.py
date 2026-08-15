"""Selection of the sales document branding theme."""

from uuid import UUID

from apps.accounting.provider import AccountingProvider
from apps.accounting.types import DocumentTheme


def _theme_by_id(themes: list[DocumentTheme], configured_id: UUID) -> DocumentTheme | None:
    return next((theme for theme in themes if theme.external_id == str(configured_id)), None)


def find_document_theme_by_id(
    provider: AccountingProvider,
    configured_id: UUID,
) -> DocumentTheme | None:
    """Return the configured theme in the connected organisation, or None.

    No fallback on purpose: production callers must not silently switch the
    theme real customers see. The fallback path is ``resolve_sales_branding_theme``.
    """
    return _theme_by_id(provider.list_document_themes(), configured_id)


def resolve_sales_branding_theme(
    provider: AccountingProvider,
    configured_id: UUID | None,
) -> DocumentTheme | None:
    """Preserve a live selection or return the provider's first theme.

    Providers return themes in their preferred order. The Xero provider orders
    them by Xero's ``SortOrder``.
    """
    themes = provider.list_document_themes()
    if not themes:
        return None
    if configured_id is not None:
        configured = _theme_by_id(themes, configured_id)
        if configured is not None:
            return configured
    return themes[0]
