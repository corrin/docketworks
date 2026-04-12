"""Accounting provider protocol — the interface every backend must implement."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from apps.client.models import Client
    from apps.job.models import Job

    from .types import (
        ContactResult,
        DocumentResult,
        InvoicePayload,
        POPayload,
        QuotePayload,
    )

logger = logging.getLogger(__name__)


class AccountingProvider(Protocol):
    """Interface that every accounting backend must implement.

    Each installation uses exactly one provider. The active provider is
    determined by settings.ACCOUNTING_BACKEND and resolved via the registry.
    """

    # --- Auth ---

    def get_auth_url(self, redirect_uri: str, state: str) -> str:
        """Return the OAuth authorization URL for this provider."""
        ...

    def exchange_code(self, code: str, state: str, session_state: str) -> dict:
        """Exchange an authorization code for tokens. Returns token dict."""
        ...

    def get_valid_token(self) -> dict | None:
        """Return a valid token, refreshing if needed. None if not connected."""
        ...

    def refresh_token(self) -> dict | None:
        """Force-refresh the current token. None if refresh fails."""
        ...

    def disconnect(self) -> None:
        """Revoke tokens and clear stored credentials."""
        ...

    # --- Contacts/Clients ---

    def create_contact(self, client: Client) -> ContactResult:
        """Create a contact in the accounting system from a local Client."""
        ...

    def update_contact(self, client: Client) -> ContactResult:
        """Update an existing contact in the accounting system."""
        ...

    def search_contact_by_name(self, name: str) -> ContactResult | None:
        """Search for a contact by name. Returns None if not found."""
        ...

    # --- Documents ---

    def create_invoice(self, payload: InvoicePayload) -> DocumentResult:
        """Create an invoice in the accounting system."""
        ...

    def delete_invoice(self, external_id: str) -> DocumentResult:
        """Delete/void an invoice in the accounting system."""
        ...

    def create_quote(self, payload: QuotePayload) -> DocumentResult:
        """Create a quote in the accounting system."""
        ...

    def delete_quote(self, external_id: str) -> DocumentResult:
        """Delete/void a quote in the accounting system."""
        ...

    def create_purchase_order(self, payload: POPayload) -> DocumentResult:
        """Create a purchase order in the accounting system."""
        ...

    def update_purchase_order(self, payload: POPayload) -> DocumentResult:
        """Update an existing purchase order in the accounting system."""
        ...

    def delete_purchase_order(self, external_id: str) -> DocumentResult:
        """Delete/void a purchase order in the accounting system."""
        ...

    # --- Attachments ---

    def attach_file_to_invoice(
        self,
        invoice_external_id: str,
        file_name: str,
        content: bytes,
    ) -> bool:
        """Attach a file to an invoice. Returns True on success."""
        ...

    def add_history_note_to_invoice(self, invoice_external_id: str, note: str) -> bool:
        """Add a history/note entry to an invoice. Returns True on success."""
        ...

    def add_history_note_to_quote(self, quote_external_id: str, note: str) -> bool:
        """Add a history/note entry to a quote. Returns True on success."""
        ...

    # --- Sync (Pull) ---

    def fetch_contacts(self, since: datetime | None = None) -> list[dict]:
        """Fetch contacts modified since the given timestamp."""
        ...

    def fetch_invoices(self, since: datetime | None = None) -> list[dict]:
        """Fetch invoices modified since the given timestamp."""
        ...

    def fetch_bills(self, since: datetime | None = None) -> list[dict]:
        """Fetch bills/supplier invoices modified since the given timestamp."""
        ...

    def fetch_accounts(self, since: datetime | None = None) -> list[dict]:
        """Fetch chart of accounts modified since the given timestamp."""
        ...

    def fetch_stock_items(self, since: datetime | None = None) -> list[dict]:
        """Fetch stock/inventory items modified since the given timestamp."""
        ...

    def fetch_purchase_orders(self, since: datetime | None = None) -> list[dict]:
        """Fetch purchase orders modified since the given timestamp."""
        ...

    def fetch_credit_notes(self, since: datetime | None = None) -> list[dict]:
        """Fetch credit notes modified since the given timestamp."""
        ...

    def fetch_quotes(self, since: datetime | None = None) -> list[dict]:
        """Fetch quotes modified since the given timestamp."""
        ...

    # --- Stock ---

    def push_stock_item(self, stock) -> str | None:
        """Push a local stock item to the accounting system. Returns external ID."""
        ...

    def fetch_all_stock_items_lookup(self) -> dict[str, dict]:
        """Fetch all stock items as a code->item lookup dict."""
        ...

    # --- Optional capabilities ---

    @property
    def supports_projects(self) -> bool:
        """Whether this provider supports project tracking (e.g. Xero Projects)."""
        ...

    @property
    def supports_payroll(self) -> bool:
        """Whether this provider supports payroll integration."""
        ...

    @property
    def provider_name(self) -> str:
        """Human-readable name of this provider (e.g. 'Xero', 'MYOB')."""
        ...

    # --- Projects (optional — check supports_projects first) ---

    def push_job_as_project(self, job: Job) -> bool:
        """Sync a job to the accounting system as a project. Returns success."""
        ...

    def sync_costlines_to_project(self, job: Job) -> bool:
        """Sync cost lines for a job to the project. Returns success."""
        ...

    # --- Accounts ---

    def get_account_code(self, account_name: str) -> str | None:
        """Look up an account code by name from the cached chart of accounts."""
        ...
