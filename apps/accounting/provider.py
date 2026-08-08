"""Accounting provider protocol — the interface every backend must implement.

ADR 0012: all accounting access goes through ``get_provider()``; SDK types
never leave the provider that owns them. The Protocol grows per-slice — it
declares only the operations a ported consumer actually calls, so an entry
here is a promise some v2 code exercises it.
"""

from collections.abc import Mapping
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from apps.company.models import Company

    from .types import ContactResult, DocumentTheme


class AccountingProvider(Protocol):
    """Interface that every accounting backend must implement.

    Each installation uses exactly one provider, resolved by
    ``registry.get_provider()`` from ``CompanyDefaults.accounting_provider``.
    """

    def get_valid_token(self) -> Mapping[str, object] | None:
        """Return a valid auth token, refreshing if needed; None means not connected."""
        ...

    def disconnect(self) -> None:
        """Sever the connection: wipe stored token material."""
        ...

    def create_contact(self, company: "Company") -> "ContactResult":
        """Create the company as a contact in the accounting system."""
        ...

    def update_contact(self, company: "Company") -> "ContactResult":
        """Push the company's current details to its existing contact (upserts)."""
        ...

    def search_contact_by_name(self, name: str) -> "ContactResult | None":
        """Find a contact by exact name; None when the name is unknown."""
        ...

    def list_document_themes(self) -> "list[DocumentTheme]":
        """Return the provider's document presentation themes, default first."""
        ...
