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

    from .types import (
        ContactResult,
        DocumentResult,
        DocumentTheme,
        InvoicePayload,
        POPayload,
        QuotePayload,
        QuotePdfDocument,
    )


class AccountingProvider(Protocol):
    """Interface that every accounting backend must implement.

    Each installation uses exactly one provider, resolved by
    ``registry.get_provider()`` from ``CompanyDefaults.accounting_provider``.
    """

    #: Human-readable backend name for error messages and logs (e.g. "Xero").
    provider_name: str

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

    def create_invoice(self, payload: "InvoicePayload") -> "DocumentResult":
        """Create a sales invoice; the result carries id/number/raw payload."""
        ...

    def delete_invoice(self, external_id: str) -> "DocumentResult":
        """Void/delete the invoice identified by ``external_id``."""
        ...

    def create_quote(self, payload: "QuotePayload") -> "DocumentResult":
        """Create a sales quote; the result carries id/number/raw payload."""
        ...

    def delete_quote(self, external_id: str) -> "DocumentResult":
        """Void/delete the quote identified by ``external_id``."""
        ...

    def download_quote_pdf(self, external_id: str) -> "QuotePdfDocument":
        """Render the quote to PDF on local disk; the caller owns the file.

        Raises rather than returning an error result: a missing PDF has no
        partial-success shape, and the one consumer (quote PDF inspection)
        needs the real cause.
        """
        ...

    def create_purchase_order(self, payload: "POPayload") -> "DocumentResult":
        """Create a purchase order."""
        ...

    def update_purchase_order(self, payload: "POPayload") -> "DocumentResult":
        """Update the purchase order named by ``payload.external_id``."""
        ...

    def delete_purchase_order(self, external_id: str) -> "DocumentResult":
        """Void/delete the purchase order identified by ``external_id``."""
        ...

    def attach_file_to_invoice(
        self, invoice_external_id: str, file_name: str, content: bytes
    ) -> bool:
        """Attach a file to an invoice; best-effort, False on failure."""
        ...

    def add_history_note_to_invoice(self, invoice_external_id: str, note: str) -> bool:
        """Add a history note to an invoice; best-effort, False on failure."""
        ...

    def add_history_note_to_quote(self, quote_external_id: str, note: str) -> bool:
        """Add a history note to a quote; best-effort, False on failure."""
        ...

    def get_account_code(self, account_name: str) -> str:
        """Resolve an account name to its code; raises when unknown."""
        ...
