"""Purchase-order push: build the payload, call the provider, persist locally.

Unlike invoices, a PO is a local-first document: the row exists before the
push, so success updates it in place (xero_id, online_url, per-line
xero_line_item_id backfill) instead of creating a mirror row.
"""

import logging
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from django.db import transaction
from django.utils import timezone
from pydantic import BaseModel, TypeAdapter

from apps.accounting.types import DocumentLineItem, DocumentResult, POPayload
from apps.accounts.models import Staff
from apps.core.errors import persist_app_error
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLine
from apps.xero.auth import get_tenant_id
from apps.xero.constants import ZERO_UUID
from apps.xero.documents.base import XeroDocumentManager, XeroDocumentResponse

logger = logging.getLogger(__name__)

# Local workflow status → the Xero PO status pushed on sync. Both received
# states map to AUTHORISED: Xero has no notion of partial receipt.
PO_STATUS_MAP = {
    "draft": "DRAFT",
    "submitted": "SUBMITTED",
    "partially_received": "AUTHORISED",
    "fully_received": "AUTHORISED",
    "deleted": "DELETED",
}


@dataclass(frozen=True)
class SentPOLine:
    """The local identity and description actually included in the request."""

    id: UUID
    description: str


@dataclass(frozen=True)
class POPushSnapshot:
    """One consistent local version, including its exact line identities."""

    version: datetime
    payload: POPayload
    lines: tuple[SentPOLine, ...]


class POResponseLine(BaseModel):
    """Identity fields from the provider's successful PO response."""

    line_item_id: UUID
    description: str


class XeroPurchaseOrderManager(XeroDocumentManager):
    """Creates, updates, and deletes purchase orders via the accounting provider."""

    def __init__(self, purchase_order: PurchaseOrder, staff: Staff) -> None:
        """Bind to a local PO; its supplier is the document's company."""
        if purchase_order.supplier is None:
            raise ValueError("Purchase order must have a supplier assigned")
        super().__init__(company=purchase_order.supplier, staff=staff, job=None)
        self.purchase_order = purchase_order

    def get_xero_id(self) -> str | None:
        """Return the stored Xero ID, treating the zero-UUID sentinel as absent."""
        xero_id = self.purchase_order.xero_id
        if xero_id and str(xero_id) != ZERO_UUID:
            return str(xero_id)
        return None

    def state_valid_for_xero(self) -> bool:
        """Refuse to create a cancelled order in Xero; allow anything else.

        Opus: v1 required ``draft`` for first creation, which is the wrong
        moment. Xero needs the order so it can reconcile the supplier's bill
        against it, and the bill arrives after the order has gone to the
        supplier — by which point the status is ``submitted``. Requiring draft
        meant the copy could only be made before it was needed and never after.
        ``deleted`` stays refused: creating an order in Xero that Docketworks
        has already cancelled would invent a payable nobody ordered.
        """
        if self.get_xero_id():
            return True
        return self.purchase_order.status != "deleted"

    def can_sync_to_xero(self) -> bool:
        """Report whether the PO carries everything a Xero PO requires."""
        if not self.company.xero_contact_id:
            logger.info(
                "PO %s cannot sync to Xero - supplier %s missing xero_contact_id",
                self.purchase_order.id,
                self.company.id,
            )
            return False
        lines = list(self.purchase_order.po_lines.all())
        if not lines:
            logger.info(
                "PO %s cannot sync to Xero - Xero requires at least one line item",
                self.purchase_order.id,
            )
            return False
        if not any(line.description and line.unit_cost is not None for line in lines):
            logger.info(
                "PO %s cannot sync to Xero - no valid lines found "
                "(need at least one with description and unit_cost)",
                self.purchase_order.id,
            )
            return False
        return True

    def validate_for_xero_sync(self) -> None:
        """Raise ValueError with the user-facing reason when the PO cannot sync."""
        if not self.company.xero_contact_id:
            raise ValueError(
                f"Supplier '{self.company.name}' is not linked to Xero. "
                "Please ensure the supplier has a valid Xero contact ID configured. "
                "You may need to sync the supplier with Xero first."
            )
        if not self.can_sync_to_xero():
            raise ValueError(
                "Purchase order is not ready for sync. Please ensure all required "
                "fields are completed (supplier, lines with descriptions and costs)."
            )

    def get_line_items(self) -> list[DocumentLineItem]:
        """One provider line per PO line, described for Xero."""
        account_code = self._get_account_code("Purchases")
        return [
            DocumentLineItem(
                description=line.xero_description,
                quantity=Decimal(str(line.quantity)),
                unit_amount=Decimal(str(line.unit_cost)) if line.unit_cost else Decimal("0"),
                item_code=line.item_code or None,
                account_code=account_code,
            )
            for line in self.purchase_order.po_lines.all()
        ]

    def build_payload(self) -> POPayload:
        """Build a provider-agnostic PO payload from the local row."""
        if not self.company.xero_contact_id:
            raise ValueError("Supplier has no Xero contact ID; validate_for_xero_sync must run")
        order_date = self.purchase_order.order_date
        if isinstance(order_date, str):
            order_date = date.fromisoformat(order_date)
        delivery_date = self.purchase_order.expected_delivery
        if isinstance(delivery_date, str):
            delivery_date = date.fromisoformat(delivery_date)

        status = PO_STATUS_MAP.get(self.purchase_order.status)
        if status is None:
            raise ValueError(
                f"Purchase order status '{self.purchase_order.status}' has no Xero mapping"
            )

        return POPayload(
            supplier_external_id=self.company.xero_contact_id,
            supplier_name=self.company.name,
            po_number=self.purchase_order.po_number,
            line_items=self.get_line_items(),
            date=order_date,
            status=status,
            delivery_date=delivery_date,
            reference=self.purchase_order.reference,
            external_id=self.get_xero_id(),
        )

    @transaction.atomic
    def _snapshot(self) -> POPushSnapshot:
        po = (
            PurchaseOrder.objects.select_for_update(of=("self",))
            .select_related("supplier")
            .prefetch_related("po_lines")
            .get(pk=self.purchase_order.pk)
        )
        if po.supplier is None:
            raise ValueError("Purchase order must have a supplier assigned")
        self.purchase_order = po
        self.company = po.supplier
        self.validate_for_xero_sync()
        return POPushSnapshot(
            version=po.updated_at,
            payload=self.build_payload(),
            lines=tuple(SentPOLine(line.id, line.xero_description) for line in po.po_lines.all()),
        )

    @transaction.atomic
    def _save_po_with_xero_data(self, result: DocumentResult, *, snapshot: POPushSnapshot) -> None:
        """Store what Xero echoed, acknowledging lines only on the sent version.

        Opus: Xero answers a write by returning the order it stored, so the
        push already holds the authoritative copy and nothing has to go back
        and ask for it. Keeping only the identity out of that answer was what
        left `xero_status`, `raw_json` and `xero_last_synced` reachable solely
        through the whole-organisation sweep — which is why the receipt spec
        ran one to check a single order.

        `status` is deliberately NOT written here. The local workflow status is
        what this push just sent, and whether goods arrived is a fact only
        Docketworks holds; the inbound transform owns the rule that protects it
        (KAN-144), and a second copy of that rule here would be a second place
        to get it wrong.
        """
        echoed = result.raw_response or {}
        po = PurchaseOrder.objects.select_for_update().get(pk=self.purchase_order.pk)
        po.online_url = result.online_url
        po.xero_status = result.document_status
        po.raw_json = echoed.get("echo")
        po.xero_last_synced = timezone.now()
        fields = ["online_url", "xero_status", "raw_json", "xero_last_synced"]
        if result.external_id and result.external_id != ZERO_UUID:
            po.xero_id = result.external_id
            po.xero_tenant_id = get_tenant_id()
            fields.extend(["xero_id", "xero_tenant_id"])
        po.save(update_fields=fields)
        self.purchase_order = po
        if po.updated_at != snapshot.version:
            logger.info("PO %s changed during push; line IDs and agreement deferred", po.id)
            return
        response_lines = echoed.get("line_items")
        if response_lines is not None:
            returned = TypeAdapter(list[POResponseLine]).validate_python(response_lines)
            self._update_line_item_ids_from_response(returned, snapshot.lines)
        po.xero_agreed_at = timezone.now()
        po.save(update_fields=["xero_agreed_at"])

    def _update_line_item_ids_from_response(
        self, response_lines: list[POResponseLine], sent_lines: tuple[SentPOLine, ...]
    ) -> None:
        """Match duplicate descriptions against distinct captured local identities."""
        remaining = list(sent_lines)
        for returned in response_lines:
            for index, sent in enumerate(remaining):
                if returned.description != sent.description:
                    continue
                PurchaseOrderLine.objects.filter(
                    pk=sent.id, purchase_order=self.purchase_order
                ).update(xero_line_item_id=returned.line_item_id)
                remaining.pop(index)
                break

    def sync_to_xero(self) -> XeroDocumentResponse:
        """Create or update the PO in Xero and store the outcome locally.

        Business failures (validation, provider rejection) return an error
        dict for the endpoint's 4xx; unexpected exceptions are persisted and
        re-raised.
        """
        try:
            snapshot = self._snapshot()
        # deliberate-swallow: an unready PO is the caller's state to fix,
        # reshaped to the 400 payload the endpoint promises
        except ValueError as exc:
            logger.warning("PO %s validation failed: %s", self.purchase_order.id, exc)
            return {
                "success": False,
                "error": str(exc),
                "error_type": "validation_error",
                "status": 400,
            }

        try:
            if snapshot.payload.external_id is not None:
                result = self.provider.update_purchase_order(snapshot.payload)
            else:
                result = self.provider.create_purchase_order(snapshot.payload)

            if not result.success:
                return {
                    "success": False,
                    "error": result.error,
                    "error_type": "api_error",
                    "status": result.status_code or 500,
                }

            self._save_po_with_xero_data(result, snapshot=snapshot)

            return {  # noqa: TRY300 -- returns a value built across the try body
                "success": True,
                "xero_id": result.external_id,
                "online_url": result.online_url,
            }
        except Exception as exc:
            logger.exception("Failed to sync PO %s", self.purchase_order.id)
            persist_app_error(exc)
            raise

    def delete_document(self) -> XeroDocumentResponse:
        """Void the PO in Xero; locally clear the Xero ID and mark it deleted."""
        xero_id = self.get_xero_id()
        if not xero_id:
            return {
                "success": False,
                "error": "Purchase Order not found in Xero (no Xero ID).",
                "status": 404,
            }

        try:
            result = self.provider.delete_purchase_order(xero_id)
            if not result.success:
                return {
                    "success": False,
                    "error": result.error,
                    "status": result.status_code or 500,
                }

            self.purchase_order.xero_id = None
            # Cleared with the id, for the same reason it is written with it:
            # a tenant claim on a row that links to nothing is a lie.
            self.purchase_order.xero_tenant_id = None
            self.purchase_order.xero_agreed_at = timezone.now()
            self.purchase_order.status = "deleted"
            self.purchase_order.save(
                update_fields=["xero_id", "xero_tenant_id", "xero_agreed_at", "status"]
            )

            return {  # noqa: TRY300 -- returns a value built across the try body
                "success": True,
                "xero_id": xero_id,
                "message": "Purchase Order deleted.",
            }
        except Exception as exc:
            logger.exception("Unexpected error deleting PO %s", self.purchase_order.id)
            persist_app_error(exc)
            raise
