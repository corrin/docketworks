"""Selection of the sales document branding theme."""

from uuid import UUID

from apps.workflow.accounting.provider import AccountingProvider
from apps.workflow.accounting.types import DocumentTheme


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

    return next(
        (
            theme
            for theme in themes
            if configured_id is not None and theme.external_id == str(configured_id)
        ),
        themes[0],
    )
