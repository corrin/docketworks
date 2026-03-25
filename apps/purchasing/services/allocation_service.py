import logging
from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Dict, Literal, Tuple, Union

from django.db import transaction
from django.db.models import F, Sum, Value
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Coalesce, Greatest

from apps.job.models import CostLine
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLine, Stock
from apps.workflow.exceptions import AlreadyLoggedException
from apps.workflow.services.error_persistence import persist_and_raise

logger = logging.getLogger(__name__)

AllocationType = Literal["stock", "job"]


class AllocationDeletionError(ValueError):
    """Custom exception for allocation deletion errors."""


@dataclass
class DeletionResult:
    success: bool
    message: str
    deleted_quantity: float
    description: str
    updated_received_quantity: float
    job_name: str | None = None


class AllocationService:
    """Service for managing delivery receipt allocations."""

    @staticmethod
    def delete_allocation(
        po_id: str,
        line_id: str,
        allocation_type: AllocationType,
        allocation_id: str,
    ) -> Dict[str, any]:
        """
        Delete a specific allocation (Stock item or CostLine) created from a delivery receipt.

        Args:
            po_id: Purchase Order ID
            line_id: Purchase Order Line ID
            allocation_type: Type of allocation ('stock' or 'job')
            allocation_id: ID of the Stock item or CostLine to delete
            user: User performing the deletion (for audit purposes)

        Returns:
            Dict with success status and details

        Raises:
            AllocationDeletionError: If deletion fails validation
            Exception: For other unexpected errors
        """
        logger.info(
            f"Starting allocation deletion - PO: {po_id}, Line: {line_id}, "
            f"Type: {allocation_type}, ID: {allocation_id}"
        )

        try:
            if allocation_type not in ("stock", "job"):
                raise AllocationDeletionError(
                    f"Invalid allocation type: {allocation_type}. Must be 'stock' or 'job'"
                )

            with transaction.atomic():
                po = AllocationService._get_po_or_error(po_id)

                po_line, obj = AllocationService._resolve_allocation_or_error(
                    po=po,
                    allocation_type=allocation_type,
                    allocation_id=allocation_id,
                )

                po_line = PurchaseOrderLine.objects.select_for_update().get(
                    id=po_line.id
                )

                if allocation_type == "stock":
                    obj = Stock.objects.select_for_update().get(id=obj.id)
                    result = AllocationService._delete_stock_allocation(po_line, obj)  # type: ignore[arg-type]
                else:
                    obj = CostLine.objects.select_for_update().get(id=obj.id)
                    result = AllocationService._delete_job_allocation(po_line, obj)  # type: ignore[arg-type]

                AllocationService._update_po_status(po)

                return asdict(result)
        except AllocationDeletionError as exc:
            logger.error("Allocation deletion validation error: %s", exc)
            raise
        except AlreadyLoggedException:
            raise
        except Exception as exc:
            logger.error("Unexpected error during allocation deletion: %s", exc)
            persist_and_raise(
                exc,
                additional_context={
                    "po_id": str(po_id),
                    "line_id": str(line_id),
                    "allocation_type": str(allocation_type),
                    "allocation_id": str(allocation_id),
                },
            )

    @staticmethod
    def get_allocation_details(
        po_id: str, allocation_type: AllocationType, allocation_id: str
    ) -> Dict[str, object]:
        try:
            if allocation_type not in ("stock", "job"):
                raise AllocationDeletionError(
                    f"Invalid allocation type: {allocation_type}"
                )

            po = AllocationService._get_po_or_error(po_id)

            if allocation_type == "stock":
                stock_item = AllocationService._get_stock_or_error(po, allocation_id)

                consuming_qs = CostLine.objects.annotate(
                    stock_id=KeyTextTransform("stock_id", "ext_refs"),
                ).filter(stock_id=str(stock_item.id))

                return {
                    "type": "stock",
                    "id": str(stock_item.id),
                    "description": stock_item.description,
                    "quantity": float(stock_item.quantity),
                    "job_name": stock_item.job.name,
                    "can_delete": not consuming_qs.exists(),
                    "consumed_by_jobs": consuming_qs.count(),
                    # Location is not mandatory so that's the reason for the fallback
                    "location": stock_item.location or "Not specified",
                }

            cost_line = AllocationService._get_costline_or_error(po, allocation_id)
            return {
                "type": "job",
                "id": str(cost_line.id),
                "description": cost_line.desc,
                "quantity": float(cost_line.quantity),
                "job_name": cost_line.cost_set.job.name,
                "can_delete": True,
                "unit_cost": float(cost_line.unit_cost),
                "unit_revenue": float(cost_line.unit_rev),
            }
        except AlreadyLoggedException:
            raise
        except Exception as exc:
            logger.error("Error getting allocation details: %s", exc)
            persist_and_raise(
                exc,
                additional_context={
                    "po_id": str(po_id),
                    "allocation_type": str(allocation_type),
                    "allocation_id": str(allocation_id),
                },
            )

    @staticmethod
    def _get_po_or_error(po_id: str) -> PurchaseOrder:
        try:
            return PurchaseOrder.objects.get(id=po_id)
        except PurchaseOrder.DoesNotExist:
            raise AllocationDeletionError(f"Purchase Order {po_id} not found")

    @staticmethod
    def _get_stock_or_error(po: PurchaseOrder, stock_id: str) -> Stock:
        try:
            return Stock.objects.select_related("source_purchase_order_line").get(
                id=stock_id,
                source="purchase_order",
                source_purchase_order_line__purchase_order=po,
            )
        except Stock.DoesNotExist:
            raise AllocationDeletionError(
                f"Stock allocation {stock_id} not found or not from PO {po.id}"
            )

    @staticmethod
    def _get_costline_or_error(po: PurchaseOrder, cost_line_id: str) -> CostLine:
        """
        CostLine created from a PO stores references in ext_refs:
            - purchase_order_id
            - purchase_order_line_id
        Verifying both here.
        """
        po_id = KeyTextTransform("purchase_order_id", "ext_refs")
        po_line_id = KeyTextTransform("purchase_order_line_id", "ext_refs")
        try:
            line = (
                CostLine.objects.select_related("cost_set__job")
                .annotate(
                    po_id=po_id,
                    po_line_id=po_line_id,
                )
                .get(id=cost_line_id, po_id=str(po.id))
            )
        except CostLine.DoesNotExist:
            raise AllocationDeletionError(
                f"Job allocation {cost_line_id} not found or not from PO {po.id}"
            )

        if not line.po_line_id:
            raise AllocationDeletionError(
                f"Cost line {cost_line_id} missing purchase_order_line_id in ext_refs"
            )

        return line

    @staticmethod
    def _resolve_allocation_or_error(
        po: PurchaseOrder,
        allocation_type: AllocationType,
        allocation_id: str,
    ) -> Tuple[PurchaseOrderLine, Union[Stock, CostLine]]:
        if allocation_type == "stock":
            stock = AllocationService._get_stock_or_error(po, allocation_id)
            return stock.source_purchase_order_line, stock

        line = AllocationService._get_costline_or_error(po, allocation_id)
        try:
            po_line = PurchaseOrderLine.objects.get(
                id=line.ext_refs["purchase_order_line_id"], purchase_order=po
            )
        except PurchaseOrderLine.DoesNotExist:
            raise AllocationDeletionError(
                f"Purchase Order Line referenced by allocation {allocation_id} not found"
            )
        return po_line, line

    @staticmethod
    def _delete_stock_allocation(
        po_line: PurchaseOrderLine,
        stock_item: Stock,
    ) -> DeletionResult:
        consuming_qs = CostLine.objects.annotate(
            stock_id=KeyTextTransform("stock_id", "ext_refs"),
        ).filter(stock_id=str(stock_item.id))

        consumed_count = consuming_qs.count()
        if consumed_count:
            raise AllocationDeletionError(
                "Cannot delete stock allocation - stock has been consumed by "
                f"{consumed_count} job(s)"
            )

        deleted_qty = Decimal(stock_item.quantity or 0)
        desc = stock_item.description

        # decrement received_quantity atomically and clamp to 0 in DB
        (
            PurchaseOrderLine.objects.filter(id=po_line.id).update(
                received_quantity=Greatest(
                    Value(Decimal("0")), F("received_quantity") - Value(deleted_qty)
                )
            )
        )
        po_line.refresh_from_db(fields=["received_quantity"])

        stock_item.delete()

        logger.info(
            "Deleted stock allocation: %s, qty=%s, PO line received now=%ss",
            desc,
            deleted_qty,
            po_line.received_quantity,
        )

        return DeletionResult(
            success=True,
            message="Stock allocation deleted successfully",
            deleted_quantity=float(deleted_qty),
            description=desc,
            updated_received_quantity=float(po_line.received_quantity),
            job_name=Stock.get_stock_holding_job().name,
        )

    @staticmethod
    def _delete_job_allocation(
        po_line: PurchaseOrderLine,
        cost_line: CostLine,
    ) -> DeletionResult:
        deleted_qty = Decimal(cost_line.quantity or 0)
        desc = cost_line.desc
        job_name = cost_line.cost_set.job.name

        (
            PurchaseOrderLine.objects.filter(id=po_line.id).update(
                received_quantity=Greatest(
                    Value(Decimal("0")), F("received_quantity") - Value(deleted_qty)
                )
            )
        )
        po_line.refresh_from_db(fields=["received_quantity"])

        cost_line.delete()

        logger.info(
            "Deleted job allocation: %s, qty=%s, job=%s, PO line received now=%s",
            desc,
            deleted_qty,
            job_name,
            po_line.received_quantity,
        )

        return DeletionResult(
            success=True,
            message="Job allocation deleted successfully",
            deleted_quantity=float(deleted_qty),
            description=desc,
            updated_received_quantity=float(po_line.received_quantity),
            job_name=job_name,
        )

    @staticmethod
    def _update_po_status(po: PurchaseOrder) -> None:
        "Compute status from aggregates (single query) and persist only if changed."
        totals = po.po_lines.aggregate(
            ordered=Coalesce(Sum("quantity"), Value(Decimal("0"))),
            received=Coalesce(Sum("received_quantity"), Value(Decimal("0"))),
        )
        ordered = totals["ordered"]
        received = totals["received"]

        logger.debug(
            "PO %s status eval: received=%s ordered=%s", po.po_number, received, ordered
        )

        new_status = po.status
        if received <= 0 and po.status != "deleted":
            new_status = "submitted"
        elif received < ordered:
            new_status = "partially_received"
        else:
            new_status = "fully_received"

        if new_status == po.status:
            logger.debug("PO %s status unchanged: %s", po.po_number, po.status)
            return

        po.status = new_status
        po.save(update_fields=["status"])
        logger.debug("Updated PO %s status to %s", po.po_number, po.status)
