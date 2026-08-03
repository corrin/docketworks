"""Stock inventory writes: CRUD helpers and ``consume_stock``.

``consume_stock`` is the ONE implementation of "take quantity off a stock row
and book it as a material cost line" (ADR 0039). Two surfaces reach it:

- ``POST /api/purchasing/stock/{id}/consume/`` — creates a new cost line.
- ``POST /api/job/cost_lines/{id}/approve/``   — approves an existing workshop
  line in place, repricing it from the stock row. That endpoint was deferred
  out of the Phase 3b-2 costing slice precisely because this function did not
  exist yet; it lands with this slice.

Stock metadata parsing (seam CLOSED by the Phase 3c-3 quoting slice): both
writes below queue ``apps.purchasing.tasks.parse_stock_item_task``, which has an
LLM fill in whatever ``metal_type``/``alloy``/``specifics`` the caller left blank
(``apps.quoting.services.stock_parser``). The enqueue is guarded by
``stock_metadata_parse_eligible`` — a row whose metadata the caller supplied in
full, or that has already had its one attempt, costs nothing — and runs on
transaction commit, so a rolled-back write is never parsed. The third stock
write site, ``allocation_service.create_stock_from_allocation``, does the same.
"""

import logging
from datetime import datetime
from decimal import Decimal
from typing import TypedDict
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Staff
from apps.core.models import CompanyDefaults
from apps.job.models import Job
from apps.job.models.costing import CostLine
from apps.purchasing.models import Stock
from apps.purchasing.services.allocation_service import ensure_actual_cost_set
from apps.purchasing.tasks import queue_metadata_parse_if_eligible

logger = logging.getLogger(__name__)


class StockItemData(TypedDict):
    """v1 StockItemSerializer row."""

    id: UUID
    item_code: str | None
    description: str
    quantity: Decimal
    unit_cost: Decimal
    unit_revenue: Decimal | None
    date: datetime
    source: str
    location: str | None
    metal_type: str | None
    alloy: str | None
    specifics: str | None
    is_active: bool
    job_id: UUID | None
    times_used: int


class StockWriteData(TypedDict, total=False):
    """The Stock fields a create/update payload may carry."""

    description: str
    quantity: Decimal
    unit_cost: Decimal
    source: str
    item_code: str | None
    unit_revenue: Decimal | None
    date: datetime
    location: str | None
    metal_type: str | None
    alloy: str | None
    specifics: str | None
    is_active: bool


def stock_item_data(stock: Stock, *, times_used: int = 0) -> StockItemData:
    """Serialise one Stock row (v1 StockItemSerializer shape)."""
    return {
        "id": stock.id,
        "item_code": stock.item_code,
        "description": stock.description,
        "quantity": stock.quantity,
        "unit_cost": stock.unit_cost,
        "unit_revenue": stock.unit_revenue,
        "date": stock.date,
        "source": stock.source,
        "location": stock.location,
        "metal_type": stock.metal_type,
        "alloy": stock.alloy,
        "specifics": stock.specifics,
        "is_active": stock.is_active,
        "job_id": stock.job_id,
        "times_used": times_used,
    }


def _apply_stock_fields(stock: Stock, data: StockWriteData) -> None:
    for field in ("description", "quantity", "unit_cost", "source", "unit_revenue", "is_active"):
        if field in data:
            setattr(stock, field, data[field])
    if "date" in data and data["date"] is not None:
        stock.date = data["date"]
    # Blank text means unset: the *_not_blank check constraints reject "".
    for field in ("item_code", "location", "metal_type", "alloy", "specifics"):
        if field in data:
            setattr(stock, field, data.get(field) or None)


def create_stock(data: StockWriteData) -> Stock:
    """Create a stock row on the stock-holding job (v1 StockViewSet.create)."""
    stock = Stock(job=Stock.get_stock_holding_job(), date=timezone.now())
    _apply_stock_fields(stock, data)
    stock.save()
    queue_metadata_parse_if_eligible(stock)
    return stock


def update_stock(stock: Stock, data: StockWriteData) -> Stock:
    """Apply a create/update payload to an existing stock row."""
    _apply_stock_fields(stock, data)
    stock.save()
    queue_metadata_parse_if_eligible(stock)
    return stock


def deactivate_stock(stock: Stock) -> None:
    """Soft-delete a stock row (v1 ``perform_destroy`` set is_active=False)."""
    Stock.objects.filter(id=stock.id).update(is_active=False)


def consume_stock(  # noqa: PLR0913 -- v1 signature (all keyword-only)
    *,
    item: Stock,
    job: Job,
    qty: Decimal,
    user: Staff,
    unit_cost: Decimal | None = None,
    unit_rev: Decimal | None = None,
    line: CostLine | None = None,
) -> CostLine:
    """Take ``qty`` off a stock row and book it as a material cost line.

    Passing ``line`` approves and reprices that existing line in place (the
    cost-line approve endpoint); otherwise a new line is created. Negative
    resulting quantities are allowed and logged, exactly as v1 (backorders and
    emergency usage are real).
    """
    if qty <= 0:
        raise ValueError("Quantity must be positive")

    with transaction.atomic():
        # Re-read under a row lock so concurrent consumption cannot double-spend.
        locked = Stock.objects.select_for_update().get(id=item.id)
        original_quantity = locked.quantity
        locked.quantity -= qty

        if locked.quantity < 0:
            logger.warning(
                "Stock item %s (%s) went negative: %s -> %s (consumed %s)",
                locked.id,
                locked.description,
                original_quantity,
                locked.quantity,
                qty,
            )
        elif locked.quantity == 0:
            logger.info(
                "Stock item %s (%s) fully consumed: %s -> 0 (consumed %s)",
                locked.id,
                locked.description,
                original_quantity,
                qty,
            )
        locked.save(update_fields=["quantity"])
        item.quantity = locked.quantity

        resolved_cost = locked.unit_cost if unit_cost is None else unit_cost
        if job.shop_job:
            # Shop jobs don't bill customers, so revenue must be zero.
            resolved_rev = Decimal("0.00")
        elif unit_rev is None:
            markup = CompanyDefaults.get_solo().materials_markup
            # Quantize to cents: CostLine.unit_rev is a 2dp column and v2's
            # CostLine.save() runs full_clean, so the raw 4dp product is a 400.
            resolved_rev = (locked.unit_cost * (Decimal("1") + markup)).quantize(Decimal("0.01"))
        else:
            resolved_rev = unit_rev

        cost_set = ensure_actual_cost_set(job, user)
        consumed_meta: dict[str, object] = {"consumed_by": str(user.id)}
        ext_refs: dict[str, object] = {"stock_id": str(locked.id)}

        if line is None:
            cost_line = CostLine(
                cost_set=cost_set,
                kind="material",
                desc=locked.description,
                quantity=qty,
                unit_cost=resolved_cost,
                unit_rev=resolved_rev,
                accounting_date=timezone.localdate(),
                ext_refs=ext_refs,
                meta=consumed_meta,
            )
            cost_line.save()
            logger.info(
                "Consumed %s of stock %s for job %s; created cost line %s",
                qty,
                locked.id,
                job.id,
                cost_line.id,
            )
            return cost_line

        line.approved = True
        line.quantity = qty
        line.desc = locked.description
        line.unit_cost = resolved_cost
        line.unit_rev = resolved_rev
        line.accounting_date = timezone.localdate()
        line.ext_refs = ext_refs
        line.meta = consumed_meta
        # v1 omitted "quantity" from update_fields here even though it had just
        # assigned it, so an approval that changed the quantity silently lost
        # the change. v2 persists every field it assigns.
        line.save(
            update_fields=[
                "approved",
                "quantity",
                "desc",
                "unit_cost",
                "unit_rev",
                "accounting_date",
                "ext_refs",
                "meta",
                "updated_at",
            ]
        )
        logger.info(
            "Approved cost line %s against stock %s for job %s (qty %s)",
            line.id,
            locked.id,
            job.id,
            qty,
        )
        return line
