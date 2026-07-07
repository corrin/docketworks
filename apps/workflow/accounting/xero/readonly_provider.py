"""Read-only Xero provider: real reads and auth, suppressed writes.

Selected by the registry when ``settings.XERO_READONLY`` is true (E2E/test
backends only). Every write logs a warning and returns a well-formed fake
result so callers — the invoice/quote/PO managers and the client-create
flow — behave exactly as with real Xero, without anything reaching the
Xero tenant. Suppressed writes are not errors: nothing here persists an
AppError.
"""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal
from typing import TYPE_CHECKING, Iterator

from django.utils import timezone

from apps.workflow.accounting.registry import register_provider
from apps.workflow.accounting.xero.provider import XeroAccountingProvider

if TYPE_CHECKING:
    from apps.client.models import Client
    from apps.workflow.accounting.types import (
        ContactResult,
        DocumentLineItem,
        DocumentResult,
        InvoicePayload,
        POPayload,
        QuotePayload,
    )

logger = logging.getLogger("xero")

_GST_RATE = Decimal("0.15")
_CENT = Decimal("0.01")


def _fake_id() -> str:
    return str(uuid.uuid4())


def _log_suppressed(operation: str, detail: str) -> None:
    logger.warning("XERO_READONLY: suppressed Xero write %s — %s", operation, detail)


def _fake_totals(line_items: list[DocumentLineItem]) -> tuple[str, str, str]:
    """Cosmetic GST-exclusive totals for stubbed documents (local display only)."""
    sub_total = sum(
        (li.quantity * li.unit_amount for li in line_items), Decimal("0")
    ).quantize(_CENT)
    tax = (sub_total * _GST_RATE).quantize(_CENT)
    total = sub_total + tax
    return str(sub_total), str(tax), str(total)


class XeroReadOnlyProvider(XeroAccountingProvider):
    """Xero provider variant whose write operations are no-ops.

    Reads, auth, and token refresh inherit unchanged from
    ``XeroAccountingProvider``.
    """

    # --- Contacts ---

    def create_contact(self, client: Client) -> ContactResult:
        from apps.workflow.accounting.types import ContactResult

        if not client.validate_for_xero():
            return ContactResult(
                success=False, error=f"Client {client.id} failed Xero validation"
            )
        # Mirror push.create_client_contact_in_xero's side effect: callers
        # (and the frontend Xero badge) read client.xero_contact_id.
        client.xero_contact_id = _fake_id()
        client.save(update_fields=["xero_contact_id"])
        _log_suppressed("create_contact", f"client {client.id} ({client.name})")
        return ContactResult(
            success=True, external_id=client.xero_contact_id, name=client.name
        )

    def update_contact(self, client: Client) -> ContactResult:
        from apps.workflow.accounting.types import ContactResult

        _log_suppressed("update_contact", f"client {client.id} ({client.name})")
        return ContactResult(
            success=True, external_id=client.xero_contact_id, name=client.name
        )

    # --- Documents ---

    def create_invoice(self, payload: InvoicePayload) -> DocumentResult:
        from apps.workflow.accounting.types import DocumentResult

        fake = _fake_id()
        number = f"INV-E2E-{fake[:8].upper()}"
        sub_total, tax, total = _fake_totals(payload.line_items)
        _log_suppressed("create_invoice", f"{number} for {payload.client_name}")
        return DocumentResult(
            success=True,
            external_id=fake,
            number=number,
            online_url=f"https://go.xero.com/app/invoicing/edit/{fake}",
            raw_response={
                "_invoice_id": fake,
                "_invoice_number": number,
                "_sub_total": sub_total,
                "_total_tax": tax,
                "_total": total,
                "_amount_due": total,
                "_contact": {"_name": payload.client_name},
                "_e2e_stub": True,
            },
        )

    def delete_invoice(self, external_id: str) -> DocumentResult:
        from apps.workflow.accounting.types import DocumentResult

        # No pre-read: the ID may be a stub that never existed in Xero.
        _log_suppressed("delete_invoice", external_id)
        return DocumentResult(success=True, external_id=external_id)

    def create_quote(self, payload: QuotePayload) -> DocumentResult:
        from apps.workflow.accounting.types import DocumentResult

        fake = _fake_id()
        number = f"QU-E2E-{fake[:8].upper()}"
        sub_total, _tax, total = _fake_totals(payload.line_items)
        _log_suppressed("create_quote", f"{number} for {payload.client_name}")
        return DocumentResult(
            success=True,
            external_id=fake,
            number=number,
            online_url=f"https://go.xero.com/app/quotes/edit/{fake}",
            raw_response={
                "_quote_id": fake,
                "_quote_number": number,
                "_sub_total": sub_total,
                "_total": total,
                "_contact": {"_name": payload.client_name},
                "_e2e_stub": True,
            },
        )

    def delete_quote(self, external_id: str) -> DocumentResult:
        from apps.workflow.accounting.types import DocumentResult

        _log_suppressed("delete_quote", external_id)
        return DocumentResult(success=True, external_id=external_id)

    def _create_or_update_purchase_order(self, payload: POPayload) -> DocumentResult:
        raise RuntimeError(
            "XERO_READONLY: real Xero PO helper reached — a write override is missing"
        )

    def create_purchase_order(self, payload: POPayload) -> DocumentResult:
        return self._stub_purchase_order(payload, _fake_id())

    def update_purchase_order(self, payload: POPayload) -> DocumentResult:
        if not payload.external_id:
            raise ValueError("Cannot update purchase order without external_id")
        return self._stub_purchase_order(payload, payload.external_id)

    @staticmethod
    def _stub_purchase_order(payload: POPayload, external_id: str) -> DocumentResult:
        from apps.workflow.accounting.types import DocumentResult

        _log_suppressed(
            "create_or_update_purchase_order",
            f"{payload.po_number} for {payload.supplier_name}",
        )
        return DocumentResult(
            success=True,
            external_id=external_id,
            number=payload.po_number,
            online_url=(
                "https://go.xero.com/Accounts/Payable/PurchaseOrders/Edit/"
                f"{external_id}/"
            ),
            raw_response={"line_items": [], "_e2e_stub": True},
        )

    def delete_purchase_order(self, external_id: str) -> DocumentResult:
        from apps.workflow.accounting.types import DocumentResult

        _log_suppressed("delete_purchase_order", external_id)
        return DocumentResult(success=True, external_id=external_id)

    # --- Attachments ---

    def attach_file_to_invoice(
        self, invoice_external_id: str, file_name: str, content: bytes
    ) -> bool:
        _log_suppressed(
            "attach_file_to_invoice",
            f"{file_name} ({len(content)} bytes) on invoice {invoice_external_id}",
        )
        return True

    # --- History Notes ---

    def _add_history_note(
        self, api_method_name: str, document_id: str, note: str
    ) -> bool:
        raise RuntimeError(
            "XERO_READONLY: real Xero history helper reached — "
            "a write override is missing"
        )

    def add_history_note_to_invoice(self, invoice_external_id: str, note: str) -> bool:
        _log_suppressed("add_history_note_to_invoice", invoice_external_id)
        return True

    def add_history_note_to_quote(self, quote_external_id: str, note: str) -> bool:
        _log_suppressed("add_history_note_to_quote", quote_external_id)
        return True

    # --- Sync ---

    def run_full_sync(self) -> Iterator[dict[str, str]]:
        # Blanket-blocked: the full sync both pushes local stock to Xero
        # (sync_local_stock_to_xero) and pulls prod data into the local DB —
        # neither belongs in a read-only test run.
        _log_suppressed("run_full_sync", "full sync skipped")
        yield {
            "datetime": timezone.now().isoformat(),
            "entity": "sync",
            "severity": "warning",
            "message": "Sync skipped: XERO_READONLY is set",
        }


register_provider("xero_readonly", XeroReadOnlyProvider)
