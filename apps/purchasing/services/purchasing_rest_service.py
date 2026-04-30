import logging
from datetime import date
from decimal import Decimal
from pprint import pprint
from typing import Any, Dict, List

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import IntegerField
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Cast, Substr
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone

from apps.client.models import Supplier, SupplierPickupAddress
from apps.job.models.costing import CostLine
from apps.job.models.job import Job
from apps.purchasing.etag import generate_po_etag, normalize_etag
from apps.purchasing.exceptions import PreconditionFailedError
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLine, Stock
from apps.purchasing.services.delivery_receipt_service import (
    _create_costline_from_allocation,
    _create_stock_from_allocation,
)
from apps.quoting.services.stock_parser import auto_parse_stock_item
from apps.workflow.models import CompanyDefaults

logger = logging.getLogger(__name__)


class PurchasingRestService:
    """Service layer for purchasing REST operations."""

    FIELD_UPDATERS = {
        "description": lambda line, value: setattr(line, "description", value),
        "item_code": lambda line, value: setattr(line, "item_code", value),
        "job_id": lambda line, value: setattr(line, "job_id", value),
        "quantity": lambda line, value: setattr(line, "quantity", value),
        "unit_cost": lambda line, value: setattr(
            line, "unit_cost", Decimal(str(value)) if value is not None else None
        ),
        "price_tbc": lambda line, value: setattr(line, "price_tbc", bool(value)),
        "metal_type": lambda line, value: setattr(line, "metal_type", value or ""),
        "alloy": lambda line, value: setattr(line, "alloy", value or ""),
        "specifics": lambda line, value: setattr(line, "specifics", value or ""),
        "location": lambda line, value: setattr(line, "location", value or ""),
        "dimensions": lambda line, value: setattr(line, "dimensions", value or ""),
    }

    @staticmethod
    def _get_valid_date(value) -> date:
        """
        Returns a valid date object. If value is None, empty, or invalid, returns today.
        """
        if not value:
            return timezone.localdate()
        if isinstance(value, date):
            return value
        if isinstance(value, str):
            try:
                return date.fromisoformat(value)
            except Exception:
                return timezone.localdate()
        return timezone.localdate()

    @staticmethod
    def _delete_lines(lines_to_delete: list[str], po: PurchaseOrder) -> None:
        """Explicitly delete lines requested by the frontend (e.g., delete button)."""
        for line_id in lines_to_delete:
            try:
                line = PurchaseOrderLine.objects.get(id=line_id, purchase_order=po)
                line.delete()
            except PurchaseOrderLine.DoesNotExist:
                continue

    @staticmethod
    def _update_supplier(supplier_id: str, po: PurchaseOrder) -> None:
        try:
            supplier = Supplier.objects.get(id=supplier_id)
            po.supplier = supplier
            logger.info(f"Updated supplier for PO {po.id} to {supplier.name}")
        except Supplier.DoesNotExist:
            logger.error(f"Invalid supplier_id {supplier_id} for PO {po.id}")
            raise

    @staticmethod
    def _update_pickup_address(
        pickup_address_id: str | None, po: PurchaseOrder
    ) -> None:
        """Update pickup address for a PO."""
        if pickup_address_id is None:
            po.pickup_address = None
            logger.info(f"Cleared pickup address for PO {po.id}")
            return

        try:
            pickup_address = SupplierPickupAddress.objects.get(
                id=pickup_address_id, is_active=True
            )
            po.pickup_address = pickup_address
            logger.info(
                f"Updated pickup address for PO {po.id} to {pickup_address.name}"
            )
        except SupplierPickupAddress.DoesNotExist:
            logger.error(
                f"Invalid pickup_address_id {pickup_address_id} for PO {po.id}"
            )
            raise

    @staticmethod
    def _update_line(line: PurchaseOrderLine, line_data: dict[str, Any]) -> None:
        for field, updater in PurchasingRestService.FIELD_UPDATERS.items():
            if field in line_data:
                updater(line, line_data[field])
        line.save()

    @staticmethod
    def _create_line(
        line_data: dict[str, Any], line_id: str, po: PurchaseOrder
    ) -> None:
        logger.info(f"Creating new line (no id or id not found): {line_id}")

        PurchaseOrderLine.objects.create(
            purchase_order=po,
            job_id=line_data.get("job_id"),
            description=line_data.get("description", ""),
            quantity=(
                Decimal(str(line_data.get("quantity", 0)))
                if line_data.get("quantity") is not None
                else Decimal("0")
            ),
            unit_cost=(
                Decimal(str(line_data["unit_cost"]))
                if line_data.get("unit_cost") is not None
                else None
            ),
            price_tbc=bool(line_data.get("price_tbc", False)),
            item_code=line_data.get("item_code"),
            metal_type=line_data.get("metal_type", ""),
            alloy=line_data.get("alloy", ""),
            specifics=line_data.get("specifics", ""),
            location=line_data.get("location", ""),
            dimensions=line_data.get("dimensions", ""),
        )
        logger.info(f"Created new line for PO {po.id}")

    @staticmethod
    def _process_line(
        line_data: dict[str, Any],
        existing_lines: dict[str, PurchaseOrderLine],
        updated_line_ids: set[str],
        po: PurchaseOrder,
    ) -> None:
        line_id = line_data.get("id")
        logger.info(f"Processing line with id: {line_id}")
        logger.info(f"Line data keys: {list(line_data.keys())}")

        if line_id:
            # Line has ID - must exist on this PO
            if str(line_id) not in existing_lines:
                raise ValidationError(
                    f"Line ID {line_id} not found on PO {po.po_number}"
                )
            logger.info(f"Updating existing line {line_id}")
            line = existing_lines[str(line_id)]
            PurchasingRestService._update_line(line, line_data)
            updated_line_ids.add(str(line_id))
            logger.info(f"Successfully updated line {line_id}")
        else:
            # No ID = new line
            PurchasingRestService._create_line(line_data, line_id, po)

    @staticmethod
    def _handle_automatic_allocation(line: PurchaseOrderLine, po: PurchaseOrder, staff):
        logger.info(
            f"Allocating lines automatically for PO {po.po_number}, line: {line}"
        )
        stock_job = Stock.get_stock_holding_job()
        defaults = CompanyDefaults.get_solo()
        retail_rate_pct = defaults.materials_markup * 100

        # Handle stock allocation first
        if str(line.job_id) == str(stock_job.id) or line.job_id is None:
            has_stock = Stock.objects.filter(
                source="purchase_order", source_purchase_order_line=line
            ).exists()

            logger.info(f"Preparing to allocate to stock - has stock? {has_stock}")
            if has_stock:
                return

            _create_stock_from_allocation(
                purchase_order=po,
                line=line,
                job=stock_job,
                qty=line.quantity,  # Since this is an automatic allocation, allocate the whole amount
                retail_rate_pct=retail_rate_pct,
                metadata={
                    "metal_type": line.metal_type or "",
                    "alloy": line.alloy or "",
                    "specifics": line.specifics or "",
                    "location": line.location or "",
                    "dimensions": line.dimensions or "",
                },
            )

            line.received_quantity = line.quantity
            line.save()
            return

        # If not stock allocation, then handle cost line allocation
        job = Job.objects.get(id=line.job_id)

        has_costlines = (
            CostLine.objects.annotate(
                po_line_id=KeyTextTransform("purchase_order_line_id", "ext_refs"),
            )
            .filter(po_line_id=str(line.id))
            .exists()
        )

        logger.info(
            f"Preparing to allocate to {job.job_number} - has costlines? {has_costlines}"
        )
        if has_costlines:
            return

        logger.info(
            "Auto allocation payload for PO %s line %s (job=%s, qty=%s, unit_cost=%s, markup_pct=%s, price_tbc=%s)",
            po.po_number,
            line.id,
            getattr(job, "job_number", None),
            line.quantity,
            line.unit_cost,
            retail_rate_pct,
            line.price_tbc,
        )

        try:
            _create_costline_from_allocation(
                purchase_order=po,
                line=line,
                job=job,
                qty=line.quantity,
                retail_rate_pct=retail_rate_pct,
                staff=staff,
            )
        except ValidationError as exc:
            logger.warning(
                "Auto allocation failed for PO %s line %s (job=%s, qty=%s, unit_cost=%s, markup_pct=%s): %s",
                po.po_number,
                line.id,
                getattr(job, "job_number", None),
                line.quantity,
                line.unit_cost,
                retail_rate_pct,
                exc,
            )
            raise

        line.received_quantity = line.quantity

        line.save()
        Job.objects.filter(pk=job.pk).untracked_update(updated_at=timezone.now())

    @staticmethod
    def _process_field(
        po: PurchaseOrder, field: Any, data: dict[str, Any], staff
    ) -> None:
        logger.info(f"Processing field {field} for PO {po.po_number}")
        match field:
            case "status":
                logger.info(f"Updating status: from {po.status} to {data[field]}")
                setattr(po, field, data[field])

                if data[field] != "fully_received":
                    return

                # If the PO is updating its status to fully received, then automatically allocate all lines
                logger.info("Processing lines for automatic allocation...")
                for line in po.po_lines.filter(quantity__gt=0):
                    PurchasingRestService._handle_automatic_allocation(line, po, staff)

            case _:
                logger.info(f"Updating field {field} to {data[field]}")
                setattr(po, field, data[field])

    @staticmethod
    def list_purchase_orders() -> List[Dict[str, Any]]:
        pos = (
            PurchaseOrder.objects.select_related("supplier", "created_by")
            .prefetch_related("po_lines__job__client")
            .order_by("-created_at")
        )
        result = []
        for po in pos:
            # Collect unique jobs with their details
            seen_jobs = {}
            for line in po.po_lines.all():
                if line.job and line.job.id not in seen_jobs:
                    seen_jobs[line.job.id] = {
                        "job_number": str(line.job.job_number),
                        "name": line.job.name,
                        "client": line.job.client.name if line.job.client else "",
                    }
            jobs = sorted(seen_jobs.values(), key=lambda j: j["job_number"])

            result.append(
                {
                    "id": str(po.id),
                    "po_number": po.po_number,
                    "status": po.status,
                    "order_date": po.order_date.isoformat(),
                    "supplier": po.supplier.name if po.supplier else "",
                    "supplier_id": str(po.supplier.id) if po.supplier else None,
                    "created_by_id": str(po.created_by.id) if po.created_by else None,
                    "created_by_name": po.created_by_name or "",
                    "jobs": jobs,
                }
            )
        return result

    @staticmethod
    def get_last_purchase_order_number() -> str | None:
        defaults = CompanyDefaults.get_solo()
        po_prefix = defaults.po_prefix or ""
        prefix_len = len(po_prefix)

        return (
            PurchaseOrder.objects.filter(po_number__regex=rf"^{po_prefix}\d+$")
            .annotate(num=Cast(Substr("po_number", prefix_len + 1), IntegerField()))
            .order_by("-num", "-created_at")
            .values_list("po_number", flat=True)
            .first()
        )

    @staticmethod
    def create_purchase_order(
        data: Dict[str, Any], *, created_by=None
    ) -> PurchaseOrder:
        supplier_id = data.get("supplier_id")
        supplier = (
            get_object_or_404(Supplier, id=data["supplier_id"]) if supplier_id else None
        )

        # Handle pickup_address_id - auto-select primary if supplier set but no address
        pickup_address = None
        pickup_address_id = data.get("pickup_address_id")
        if pickup_address_id:
            pickup_address = get_object_or_404(
                SupplierPickupAddress, id=pickup_address_id, is_active=True
            )
        elif supplier:
            # Auto-select primary address if supplier is set and no address specified
            pickup_address = SupplierPickupAddress.objects.filter(
                client=supplier, is_primary=True, is_active=True
            ).first()

        order_date = data.get("order_date")
        if not order_date:
            order_date = timezone.localdate()
        else:
            order_date = PurchasingRestService._get_valid_date(order_date)

        expected_delivery = PurchasingRestService._get_valid_date(
            data.get("expected_delivery")
        )

        po = PurchaseOrder.objects.create(
            supplier=supplier,
            pickup_address=pickup_address,
            reference=data.get("reference", ""),
            order_date=order_date,
            expected_delivery=expected_delivery,
            created_by=created_by,
        )

        for line in data.get("lines", []):
            price_tbc = bool(line.get("price_tbc", False))
            unit_cost = line.get("unit_cost")
            match price_tbc, unit_cost is not None:
                case (True, _):
                    unit_cost = None
                case (False, True):
                    unit_cost = Decimal(str(unit_cost))

            PurchaseOrderLine.objects.create(
                purchase_order=po,
                job_id=line.get("job_id"),
                description=line.get("description", ""),
                quantity=(
                    Decimal(str(line.get("quantity", 0)))
                    if line.get("quantity") is not None
                    else Decimal("0")
                ),
                unit_cost=unit_cost,
                price_tbc=price_tbc,
                item_code=line.get("item_code"),
                metal_type=line.get("metal_type", ""),
                alloy=line.get("alloy", ""),
                specifics=line.get("specifics", ""),
                location=line.get("location", ""),
            )
        return po

    @staticmethod
    def update_purchase_order(
        po_id: str,
        data: Dict[str, Any],
        *,
        staff,
        expected_etag: str | None = None,
    ) -> PurchaseOrder:
        expected_normalized = normalize_etag(expected_etag) if expected_etag else None

        with transaction.atomic():
            try:
                po = (
                    PurchaseOrder.objects.select_for_update(of=("self",))
                    .select_related("supplier")
                    .prefetch_related("po_lines")
                    .get(id=po_id)
                )
            except PurchaseOrder.DoesNotExist as exc:
                raise Http404(f"PurchaseOrder {po_id} not found") from exc

            current_etag = normalize_etag(generate_po_etag(po))
            if expected_normalized is not None and expected_normalized != current_etag:
                raise PreconditionFailedError(
                    "Purchase order modified since it was fetched."
                )

            # Handle explicit line deletion (user clicked delete button)
            lines_to_delete = data.get("lines_to_delete")
            if lines_to_delete:
                PurchasingRestService._delete_lines(lines_to_delete, po)

            # Handle supplier updates
            supplier_id = data.get("supplier_id")
            if supplier_id:
                PurchasingRestService._update_supplier(supplier_id, po)

            # Handle pickup address updates
            if "pickup_address_id" in data:
                PurchasingRestService._update_pickup_address(
                    data.get("pickup_address_id"), po
                )

            existing_lines = {str(line.id): line for line in po.po_lines.all()}
            updated_line_ids = set()

            logger.info(f"Processing {len(data.get('lines', []))} lines for PO {po.id}")
            logger.info(f"Existing lines: {list(existing_lines.keys())}")

            for line_data in data.get("lines", []):
                line_id = line_data.get("id")
                logger.info(f"Processing line with id: {line_id}")
                logger.info(f"Line data keys: {list(line_data.keys())}")
                PurchasingRestService._process_line(
                    line_data, existing_lines, updated_line_ids, po
                )

            for field in ["reference", "expected_delivery", "status"]:
                if field in data:
                    PurchasingRestService._process_field(po, field, data, staff)

            po.save()
            po.refresh_from_db()

            logger.info("PO after update:")
            pprint(po.__dict__)

            logger.info(f"Update complete. Updated line IDs: {updated_line_ids}")
            return po

    @staticmethod
    def list_stock() -> List[Dict[str, Any]]:
        return Stock.objects.filter(is_active=True)

    @staticmethod
    def create_stock(data: dict) -> Stock:
        required = ["description", "quantity", "unit_cost", "source"]
        if not all(k in data for k in required):
            raise ValueError("Missing required fields")

        stock_item = Stock.objects.create(
            job=Stock.get_stock_holding_job(),
            description=data["description"],
            quantity=Decimal(str(data["quantity"])),
            unit_cost=Decimal(str(data["unit_cost"])),
            source=data["source"],
            metal_type=data.get("metal_type", ""),
            alloy=data.get("alloy", ""),
            specifics=data.get("specifics", ""),
            location=data.get("location", ""),
            is_active=True,
        )

        # Parse the stock item to extract additional metadata

        auto_parse_stock_item(stock_item)

        return stock_item

    @staticmethod
    def list_xero_items() -> list[dict]:
        from apps.workflow.api.xero.xero import get_xero_items

        cached = cache.get("xero_items")
        if cached is not None:
            return cached
        try:
            raw = get_xero_items()
            items = []
            for i in raw:
                items.append(
                    {
                        "id": i.item_id if i.item_id else None,
                        "code": i.code if i.code else None,
                        "name": i.name if i.name else None,
                        "unit_cost": (
                            i.purchase_details.unit_price
                            if i.purchase_details and i.purchase_details.unit_price
                            else None
                        ),
                    }
                )
            return items
        except Exception:
            logger.exception("Failed to fetch Xero items")
            return []
