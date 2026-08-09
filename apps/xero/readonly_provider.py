"""Read-only Xero provider: real reads and auth, suppressed writes.

Selected by the registry when ``settings.XERO_READONLY`` is true (E2E/test
backends only). Every write logs a warning and returns a well-formed fake
result so callers — the company-create flow today, document managers when
they port — behave exactly as with real Xero, without anything reaching the
Xero tenant. Suppressed writes are not errors: nothing here persists an
AppError.
"""

import logging
import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from apps.accounting.types import (
    ContactResult,
    DocumentLineItem,
    DocumentResult,
    InvoicePayload,
    POPayload,
)
from apps.core.models import CompanyDefaults
from apps.xero.provider import XeroAccountingProvider

if TYPE_CHECKING:
    from apps.company.models import Company

logger = logging.getLogger(__name__)

_CENT = Decimal("0.01")


def _fake_id() -> str:
    return str(uuid.uuid4())


def _log_suppressed(operation: str, detail: str) -> None:
    logger.warning("XERO_READONLY: suppressed Xero write %s — %s", operation, detail)


def _fake_totals(line_items: list[DocumentLineItem]) -> tuple[str, str, str]:
    """Cosmetic GST-exclusive totals for stubbed documents (local display only)."""
    sub_total = sum((li.quantity * li.unit_amount for li in line_items), Decimal("0")).quantize(
        _CENT
    )
    tax = (sub_total * CompanyDefaults.get_solo().gst_rate).quantize(_CENT)
    total = sub_total + tax
    return str(sub_total), str(tax), str(total)


class XeroReadOnlyProvider(XeroAccountingProvider):
    """Xero provider variant whose write operations are no-ops.

    Reads, auth, and token refresh inherit unchanged from
    ``XeroAccountingProvider``.
    """

    # --- Contacts ---

    def create_contact(self, company: "Company") -> ContactResult:
        """Assign a synthetic contact id without touching the tenant."""
        if not company.validate_for_xero():
            return ContactResult(
                success=False, error=f"Company {company.id} failed Xero validation"
            )
        # Mirror contacts.create_company_contact_in_xero's side effect: callers
        # (and the frontend Xero badge) read company.xero_contact_id.
        company.xero_contact_id = _fake_id()
        company.save(update_fields=["xero_contact_id"])
        _log_suppressed("create_contact", f"company {company.id} ({company.name})")
        return ContactResult(success=True, external_id=company.xero_contact_id, name=company.name)

    def update_contact(self, company: "Company") -> ContactResult:
        """Suppress the push; upsert a synthetic id when the company has none."""
        # The live provider validates every update (sync_company_to_xero);
        # skipping it here would make readonly tests pass an update
        # production rejects.
        if not company.validate_for_xero():
            return ContactResult(
                success=False, error=f"Company {company.id} failed Xero validation"
            )
        if not company.xero_contact_id:
            # Mirror contacts.sync_company_to_xero: updating a company that has
            # no contact ID is an upsert — it creates the contact and assigns
            # a fresh ID rather than succeeding with a missing external_id.
            return self.create_contact(company)
        _log_suppressed("update_contact", f"company {company.id} ({company.name})")
        return ContactResult(success=True, external_id=company.xero_contact_id, name=company.name)

    # --- Documents ---

    def create_invoice(self, payload: InvoicePayload) -> DocumentResult:
        """Fabricate a created invoice; nothing reaches the tenant.

        The raw_response mirrors process_xero_data's underscore-prefixed keys —
        the invoice manager reads ``_sub_total``/``_total_tax``/``_total``/
        ``_amount_due`` from it to populate the local Invoice row, so the
        E2E balance assertions settle exactly as they would against real Xero.
        """
        fake = _fake_id()
        number = f"INV-E2E-{fake[:8].upper()}"
        sub_total, tax, total = _fake_totals(payload.line_items)
        _log_suppressed("create_invoice", f"{number} for {payload.company_name}")
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
                "_contact": {"_name": payload.company_name},
                "_e2e_stub": True,
            },
        )

    def delete_invoice(self, external_id: str) -> DocumentResult:
        """Suppress the delete.

        No pre-read: the ID may be a stub that never existed in Xero, so the
        live path's get_invoice would 404.
        """
        _log_suppressed("delete_invoice", external_id)
        return DocumentResult(success=True, external_id=external_id)

    # --- Purchase orders ---

    @staticmethod
    def _stub_purchase_order(payload: POPayload, external_id: str) -> DocumentResult:
        _log_suppressed(
            "create_or_update_purchase_order", f"{payload.po_number} for {payload.supplier_name}"
        )
        return DocumentResult(
            success=True,
            external_id=external_id,
            number=payload.po_number,
            online_url=(f"https://go.xero.com/Accounts/Payable/PurchaseOrders/Edit/{external_id}/"),
            # Empty line_items: no fabricated per-line ids, so the manager's
            # xero_line_item_id backfill is a no-op under readonly.
            raw_response={"line_items": [], "_e2e_stub": True},
        )

    def create_purchase_order(self, payload: POPayload) -> DocumentResult:
        """Fabricate a created purchase order; nothing reaches the tenant."""
        return self._stub_purchase_order(payload, _fake_id())

    def update_purchase_order(self, payload: POPayload) -> DocumentResult:
        """Suppress the update; echo the existing external id."""
        if not payload.external_id:
            raise ValueError("Cannot update purchase order without external_id")
        return self._stub_purchase_order(payload, payload.external_id)

    def delete_purchase_order(self, external_id: str) -> DocumentResult:
        """Suppress the delete; no pre-read (the ID may be a stub)."""
        _log_suppressed("delete_purchase_order", external_id)
        return DocumentResult(success=True, external_id=external_id)

    # --- Attachments ---

    def attach_file_to_invoice(
        self, invoice_external_id: str, file_name: str, content: bytes
    ) -> bool:
        """Suppress the upload; report success as the live path would."""
        _log_suppressed(
            "attach_file_to_invoice",
            f"{file_name} ({len(content)} bytes) on invoice {invoice_external_id}",
        )
        return True

    # --- History notes ---

    def _add_history_note(
        self,
        document_kind: str,  # noqa: ARG002 -- signature must shadow the live helper exactly
        document_id: str,  # noqa: ARG002
        note: str,  # noqa: ARG002
    ) -> bool:
        # Tripwire, not a silent no-op: a new public note method that forgets
        # its readonly override would otherwise write to the live tenant path.
        raise RuntimeError(
            "XERO_READONLY: real Xero history helper reached — a write override is missing"
        )

    def add_history_note_to_invoice(
        self,
        invoice_external_id: str,
        note: str,  # noqa: ARG002 -- suppressed write; the note goes nowhere by design
    ) -> bool:
        """Suppress the note; report success as the live path would."""
        _log_suppressed("add_history_note_to_invoice", invoice_external_id)
        return True

    def add_history_note_to_quote(
        self,
        quote_external_id: str,
        note: str,  # noqa: ARG002 -- suppressed write; the note goes nowhere by design
    ) -> bool:
        """Suppress the note; report success as the live path would."""
        _log_suppressed("add_history_note_to_quote", quote_external_id)
        return True
