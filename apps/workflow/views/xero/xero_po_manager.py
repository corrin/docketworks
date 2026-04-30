# workflow/views/xero_po_manager.py
import logging
from datetime import date
from decimal import Decimal

from django.utils import timezone

from apps.accounts.models import Staff
from apps.purchasing.models import PurchaseOrder
from apps.workflow.accounting.types import DocumentLineItem, POPayload
from apps.workflow.services.error_persistence import persist_app_error

from .xero_base_manager import XeroDocumentManager

logger = logging.getLogger("xero")


class XeroPurchaseOrderManager(XeroDocumentManager):
    """Xero PO sync handler using the accounting provider."""

    def __init__(self, purchase_order: PurchaseOrder, staff: Staff):
        super().__init__(client=purchase_order.supplier, staff=staff, job=None)
        self.purchase_order = purchase_order

    def can_sync_to_xero(self) -> bool:
        """Check if PO is ready for Xero sync (has required fields)."""
        if not self.purchase_order.supplier:
            logger.info(
                "PO %s cannot sync to Xero - missing supplier", self.purchase_order.id
            )
            return False

        if not self.purchase_order.supplier.xero_contact_id:
            logger.info(
                "PO %s cannot sync to Xero - supplier %s missing xero_contact_id",
                self.purchase_order.id,
                self.purchase_order.supplier.id,
            )
            return False

        # First check if we have any lines at all
        if not self.purchase_order.po_lines.exists():
            logger.info(
                "PO %s cannot sync to Xero - Xero requires at least one line item",
                self.purchase_order.id,
            )
            return False

        # Then check if at least one line has required fields
        has_valid_line = any(
            line.description and line.unit_cost is not None
            for line in self.purchase_order.po_lines.all()
        )

        if not has_valid_line:
            logger.info(
                (
                    "PO %s cannot sync to Xero - no valid lines found "
                    "(need at least one with description and unit_cost)"
                ),
                self.purchase_order.id,
            )
            return False

        return True

    def get_xero_id(self) -> str | None:
        """Returns the Xero ID if the local PO has one."""
        zero_uuid = "00000000-0000-0000-0000-000000000000"
        if (
            self.purchase_order
            and self.purchase_order.xero_id
            and str(self.purchase_order.xero_id) != zero_uuid
        ):
            return str(self.purchase_order.xero_id)
        return None

    def state_valid_for_xero(self) -> bool:
        """
        Checks if the purchase order is in a valid state for operations.
        For initial creation, we require 'draft' status.
        For updates, we allow any status as long as the PO has a Xero ID.
        """
        # If we're updating an existing PO, allow any status
        if self.get_xero_id():
            return True

        # For initial creation/sending, we require 'draft'
        return self.purchase_order.status == "draft"

    def get_line_items(self) -> list[DocumentLineItem]:
        """
        Generates purchase order-specific line items for the provider payload.
        """
        logger.info("Starting get_line_items for PO")
        line_items = []
        account_code = self._get_account_code("Purchases")

        if not self.purchase_order:
            logger.error("Purchase order object is missing in get_line_items.")
            return []

        for line in self.purchase_order.po_lines.all():
            line_item_data = {
                "description": line.xero_description,
                "quantity": Decimal(str(line.quantity)),
                "unit_amount": (
                    Decimal(str(line.unit_cost)) if line.unit_cost else Decimal("0")
                ),
            }

            if line.item_code:
                line_item_data["item_code"] = line.item_code

            if account_code:
                line_item_data["account_code"] = account_code

            try:
                line_items.append(DocumentLineItem(**line_item_data))
            except Exception as exc:
                persist_app_error(exc)
                logger.error(
                    f"Error creating DocumentLineItem for PO line {line.id}: {exc}",
                    exc_info=True,
                )

        logger.info(
            f"Finished get_line_items for PO. Prepared {len(line_items)} items."
        )
        return line_items

    def build_payload(self) -> POPayload:
        """Build a provider-agnostic PO payload."""
        line_items = self.get_line_items()
        order_date = self.purchase_order.order_date
        if isinstance(order_date, str):
            order_date = date.fromisoformat(order_date)

        status_map = {
            "draft": "DRAFT",
            "submitted": "SUBMITTED",
            "partially_received": "AUTHORISED",
            "fully_received": "AUTHORISED",
            "deleted": "DELETED",
        }

        delivery_date = None
        if self.purchase_order.expected_delivery:
            delivery_date = self.purchase_order.expected_delivery
            if isinstance(delivery_date, str):
                delivery_date = date.fromisoformat(delivery_date)

        return POPayload(
            supplier_external_id=self.client.xero_contact_id,
            supplier_name=self.client.name,
            po_number=self.purchase_order.po_number,
            line_items=line_items,
            date=order_date,
            status=status_map.get(self.purchase_order.status, "DRAFT"),
            delivery_date=delivery_date,
            reference=self.purchase_order.reference,
            external_id=self.get_xero_id(),
        )

    def _save_po_with_xero_data(
        self, xero_id: str | None, online_url: str | None, updated_date_utc=None
    ) -> None:
        """
        Saves PO data with accounting system information.

        Args:
            xero_id: External ID to be saved, None for not saving ID
            online_url: Online URL for the document
            updated_date_utc: External update date, or None to use now()
        """
        update_fields = ["online_url"]

        self.purchase_order.online_url = online_url

        if updated_date_utc:
            self.purchase_order.xero_last_synced = updated_date_utc
            update_fields.append("xero_last_synced")
        else:
            self.purchase_order.xero_last_synced = timezone.now()

        if xero_id:
            self.purchase_order.xero_id = xero_id
            update_fields.append("xero_id")

        self.purchase_order.save(update_fields=update_fields)

    def _update_line_item_ids_from_response(
        self, response_line_items: list[dict]
    ) -> None:
        """
        Update local PurchaseOrderLine records with line_item_ids from response.

        Matches lines by description (with job number prefix if applicable).
        Uses a list-based approach to handle duplicate descriptions correctly.
        """
        if not response_line_items:
            return

        # Build a list of (xero_description, line) tuples for matching
        local_lines = [
            (line.xero_description, line) for line in self.purchase_order.po_lines.all()
        ]

        updated_count = 0
        for xero_line in response_line_items:
            xero_line_item_id = xero_line.get("line_item_id")
            xero_description = xero_line.get("description")

            if not xero_line_item_id or not xero_description:
                continue

            # Find first matching local line and remove it from the list
            for i, (desc, local_line) in enumerate(local_lines):
                if desc == xero_description:
                    if local_line.xero_line_item_id != xero_line_item_id:
                        local_line.xero_line_item_id = xero_line_item_id
                        local_line.save(update_fields=["xero_line_item_id"])
                        updated_count += 1
                    local_lines.pop(i)
                    break

        logger.info(
            f"Updated {updated_count} line item IDs for PO {self.purchase_order.id}"
        )

    def sync_to_xero(self) -> dict:
        """Sync current PO state to the accounting system and update local model.

        Returns:
            dict: Always returns a dict with:
                - success (bool): Whether the operation succeeded
                - On success: xero_id and online_url fields
                - On failure: error and error_type fields
        """
        logger.info(
            f"Starting sync_to_xero for PO {self.purchase_order.id}",
            extra={
                "purchase_order_id": str(self.purchase_order.id),
                "po_number": self.purchase_order.po_number,
                "supplier_id": (
                    str(self.purchase_order.supplier.id)
                    if self.purchase_order.supplier
                    else None
                ),
                "has_xero_id": bool(self.get_xero_id()),
            },
        )

        # Validate PO readiness before attempting sync
        try:
            self.validate_for_xero_sync()
        except ValueError as e:
            logger.warning(
                f"PO {self.purchase_order.id} validation failed: {str(e)}",
                extra={
                    "purchase_order_id": str(self.purchase_order.id),
                    "validation_error": str(e),
                },
            )
            return {
                "success": False,
                "error": str(e),
                "error_type": "validation_error",
                "status": 400,
            }

        try:
            payload = self.build_payload()
            action = "update" if self.get_xero_id() else "create"

            if action == "update":
                result = self.provider.update_purchase_order(payload)
            else:
                result = self.provider.create_purchase_order(payload)

            if not result.success:
                return {
                    "success": False,
                    "error": result.error,
                    "error_type": "api_error",
                    "status": result.status_code or 500,
                    "validation_errors": result.validation_errors,
                }

            # Update local PO with data from response
            self._save_po_with_xero_data(result.external_id, result.online_url, None)

            # Update line item IDs from response
            raw = result.raw_response or {}
            if "line_items" in raw:
                self._update_line_item_ids_from_response(raw["line_items"])

            return {
                "success": True,
                "xero_id": result.external_id,
                "online_url": result.online_url,
            }
        except Exception as exc:
            persist_app_error(exc)
            logger.error(
                f"Failed to sync PO {self.purchase_order.id}: {str(exc)}",
                exc_info=True,
            )
            return {
                "success": False,
                "error": str(exc),
                "error_type": type(exc).__name__,
                "status": 500,
            }

    def delete_document(self) -> dict:
        """
        Deletes the purchase order via the provider.
        Updates the local PurchaseOrder record by clearing the Xero ID.
        """
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
            self.purchase_order.xero_last_synced = timezone.now()
            self.purchase_order.status = "deleted"
            self.purchase_order.save(
                update_fields=["xero_id", "xero_last_synced", "status"]
            )

            return {"success": True, "action": "delete"}
        except Exception as exc:
            persist_app_error(exc)
            logger.error(
                f"Unexpected error deleting PO {self.purchase_order.id}: {str(exc)}",
                exc_info=True,
            )
            return {
                "success": False,
                "error": f"An unexpected error occurred during deletion: {str(exc)}",
                "status": 500,
            }

    def validate_for_xero_sync(self):
        """
        Validates that the purchase order and supplier are ready for sync.

        Raises:
            ValueError: If validation fails with descriptive message
        """
        if not self.purchase_order:
            raise ValueError("Purchase order is missing")

        supplier = self.purchase_order.supplier
        if not supplier:
            raise ValueError("Purchase order must have a supplier assigned")

        if not supplier.xero_contact_id:
            raise ValueError(
                f"Supplier '{supplier.name}' is not linked to Xero. "
                f"Please ensure the supplier has a valid Xero contact ID configured. "
                f"You may need to sync the supplier with Xero first."
            )

        # Additional validation for PO readiness
        if not self.can_sync_to_xero():
            raise ValueError(
                "Purchase order is not ready for sync. "
                "Please ensure all required fields are completed (supplier, lines with descriptions and costs)."
            )
