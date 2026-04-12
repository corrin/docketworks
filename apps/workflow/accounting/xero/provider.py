"""Xero accounting provider — delegates to existing apps/workflow/api/xero/ code."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

from apps.workflow.accounting.registry import register_provider

if TYPE_CHECKING:
    from apps.client.models import Client
    from apps.job.models import Job
    from apps.workflow.accounting.types import (
        ContactResult,
        DocumentResult,
        InvoicePayload,
        POPayload,
        QuotePayload,
    )

logger = logging.getLogger("xero")


class XeroAccountingProvider:
    """Xero implementation of the AccountingProvider protocol.

    Phase 1: Registered but not yet wired into callers.
    Delegates to existing functions in apps/workflow/api/xero/.
    """

    @property
    def provider_name(self) -> str:
        return "Xero"

    @property
    def supports_projects(self) -> bool:
        from django.conf import settings

        return getattr(settings, "XERO_SYNC_PROJECTS", False)

    @property
    def supports_payroll(self) -> bool:
        return True

    # --- Auth ---

    def get_auth_url(self, redirect_uri: str, state: str) -> str:
        from apps.workflow.api.xero.auth import get_authentication_url

        return get_authentication_url(redirect_uri, state)

    def exchange_code(self, code: str, state: str, session_state: str) -> dict:
        from apps.workflow.api.xero.auth import exchange_code_for_token

        return exchange_code_for_token(code, state, session_state)

    def get_valid_token(self) -> dict | None:
        from apps.workflow.api.xero.auth import get_valid_token

        return get_valid_token()

    def refresh_token(self) -> dict | None:
        from apps.workflow.api.xero.auth import refresh_token

        return refresh_token()

    def disconnect(self) -> None:
        from apps.workflow.models import XeroToken

        XeroToken.objects.all().delete()

    # --- Contacts ---

    def create_contact(self, client: Client) -> ContactResult:
        from apps.workflow.accounting.types import ContactResult
        from apps.workflow.api.xero.push import create_client_contact_in_xero

        try:
            xero_contact_id = create_client_contact_in_xero(client)
            return ContactResult(
                success=True,
                external_id=xero_contact_id,
                name=client.name,
            )
        except Exception as exc:
            return ContactResult(success=False, error=str(exc))

    def update_contact(self, client: Client) -> ContactResult:
        from apps.workflow.accounting.types import ContactResult
        from apps.workflow.api.xero.push import sync_client_to_xero

        try:
            sync_client_to_xero(client)
            return ContactResult(
                success=True,
                external_id=client.xero_contact_id,
                name=client.name,
            )
        except Exception as exc:
            return ContactResult(success=False, error=str(exc))

    def search_contact_by_name(self, name: str) -> ContactResult | None:
        from apps.workflow.accounting.types import ContactResult
        from apps.workflow.api.xero.push import get_all_xero_contacts

        contacts = get_all_xero_contacts()
        for contact in contacts:
            if contact.get("name", "").lower() == name.lower():
                return ContactResult(
                    success=True,
                    external_id=contact.get("contact_id"),
                    name=contact.get("name"),
                )
        return None

    # --- Documents (stubs for Phase 1 — wired in Phase 2) ---

    def create_invoice(self, payload: InvoicePayload) -> DocumentResult:
        raise NotImplementedError("Invoice creation via provider wired in Phase 2")

    def delete_invoice(self, external_id: str) -> DocumentResult:
        raise NotImplementedError("Invoice deletion via provider wired in Phase 2")

    def create_quote(self, payload: QuotePayload) -> DocumentResult:
        raise NotImplementedError("Quote creation via provider wired in Phase 2")

    def delete_quote(self, external_id: str) -> DocumentResult:
        raise NotImplementedError("Quote deletion via provider wired in Phase 2")

    def create_purchase_order(self, payload: POPayload) -> DocumentResult:
        raise NotImplementedError("PO creation via provider wired in Phase 2")

    def update_purchase_order(self, payload: POPayload) -> DocumentResult:
        raise NotImplementedError("PO update via provider wired in Phase 2")

    def delete_purchase_order(self, external_id: str) -> DocumentResult:
        raise NotImplementedError("PO deletion via provider wired in Phase 2")

    # --- Attachments (stubs for Phase 1) ---

    def attach_file_to_invoice(
        self, invoice_external_id: str, file_name: str, content: bytes
    ) -> bool:
        raise NotImplementedError("Attachments via provider wired in Phase 2")

    def add_history_note_to_invoice(self, invoice_external_id: str, note: str) -> bool:
        raise NotImplementedError("History notes via provider wired in Phase 2")

    def add_history_note_to_quote(self, quote_external_id: str, note: str) -> bool:
        raise NotImplementedError("History notes via provider wired in Phase 2")

    # --- Sync (stubs for Phase 1 — wired in Phase 4) ---

    def fetch_contacts(self, since: datetime | None = None) -> list[dict]:
        raise NotImplementedError("Contact fetch via provider wired in Phase 4")

    def fetch_invoices(self, since: datetime | None = None) -> list[dict]:
        raise NotImplementedError("Invoice fetch via provider wired in Phase 4")

    def fetch_bills(self, since: datetime | None = None) -> list[dict]:
        raise NotImplementedError("Bill fetch via provider wired in Phase 4")

    def fetch_accounts(self, since: datetime | None = None) -> list[dict]:
        raise NotImplementedError("Account fetch via provider wired in Phase 4")

    def fetch_stock_items(self, since: datetime | None = None) -> list[dict]:
        raise NotImplementedError("Stock fetch via provider wired in Phase 4")

    def fetch_purchase_orders(self, since: datetime | None = None) -> list[dict]:
        raise NotImplementedError("PO fetch via provider wired in Phase 4")

    def fetch_credit_notes(self, since: datetime | None = None) -> list[dict]:
        raise NotImplementedError("Credit note fetch via provider wired in Phase 4")

    def fetch_quotes(self, since: datetime | None = None) -> list[dict]:
        raise NotImplementedError("Quote fetch via provider wired in Phase 4")

    # --- Stock ---

    def push_stock_item(self, stock) -> str | None:
        raise NotImplementedError("Stock push via provider wired in Phase 4")

    def fetch_all_stock_items_lookup(self) -> dict[str, dict]:
        raise NotImplementedError("Stock lookup via provider wired in Phase 4")

    # --- Projects ---

    def push_job_as_project(self, job: Job) -> bool:
        raise NotImplementedError("Project push via provider wired in Phase 4")

    def sync_costlines_to_project(self, job: Job) -> bool:
        raise NotImplementedError("Costline sync via provider wired in Phase 4")

    # --- Accounts ---

    def get_account_code(self, account_name: str) -> str | None:
        from apps.workflow.models import XeroAccount

        try:
            return XeroAccount.objects.get(account_name=account_name).account_code
        except XeroAccount.DoesNotExist:
            return None


# Auto-register when this module is imported
register_provider("xero", XeroAccountingProvider)
