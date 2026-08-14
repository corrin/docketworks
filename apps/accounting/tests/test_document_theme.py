"""resolve_sales_branding_theme: keep a live selection, else take the first theme."""

from unittest.mock import MagicMock
from uuid import UUID

from apps.accounting.services.document_theme import resolve_sales_branding_theme
from apps.accounting.types import DocumentTheme

FIRST = DocumentTheme(
    external_id="11111111-1111-1111-1111-111111111111", name="Standard", is_default=True
)
SECOND = DocumentTheme(
    external_id="22222222-2222-2222-2222-222222222222", name="Alternate", is_default=False
)


def _provider(themes: list[DocumentTheme]) -> MagicMock:
    provider = MagicMock()
    provider.list_document_themes.return_value = themes
    return provider


def test_returns_none_when_provider_has_no_themes() -> None:
    assert resolve_sales_branding_theme(_provider([]), None) is None


def test_returns_first_theme_when_nothing_configured() -> None:
    assert resolve_sales_branding_theme(_provider([FIRST, SECOND]), None) == FIRST


def test_keeps_configured_theme_when_still_live() -> None:
    resolved = resolve_sales_branding_theme(_provider([FIRST, SECOND]), UUID(SECOND.external_id))

    assert resolved == SECOND


def test_falls_back_to_first_theme_when_configured_id_is_gone() -> None:
    # A demo org reset drops the configured theme; setup must re-point rather
    # than leave the installation unable to invoice.
    resolved = resolve_sales_branding_theme(
        _provider([FIRST, SECOND]), UUID("33333333-3333-3333-3333-333333333333")
    )

    assert resolved == FIRST
