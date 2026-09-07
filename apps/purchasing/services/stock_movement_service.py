"""The single writer of inventory balances and their durable counterparts."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from django.db import transaction
from django.db.models import Sum

from apps.accounts.models import Staff
from apps.core.errors import InvalidInputError
from apps.job.models import Job
from apps.job.models.costing import CostLine
from apps.purchasing.models import Stock, StockMovement, StocktakeLine

MovementKind = Literal["opening", "receipt", "receipt_reversal", "issue", "return", "stocktake"]


@dataclass(frozen=True)
class MovementContext:
    """Provenance supplied by the workflow that owns the movement."""

    kind: MovementKind
    reason: str
    actor: Staff | None = None
    counterpart_job: Job | None = None
    cost_line: CostLine | None = None
    stocktake_line: StocktakeLine | None = None
    reverses: StockMovement | None = None


@transaction.atomic
def move_stock(stock: Stock, change: Decimal, context: MovementContext) -> StockMovement:
    """Lock, record and project one movement; negative inventory remains permitted."""
    locked = Stock.objects.select_for_update().get(pk=stock.pk)
    if change != change.quantize(Decimal("0.001")):
        raise InvalidInputError("Stock quantities support at most three decimal places.")
    if not context.reason.strip():
        raise InvalidInputError("A stock movement requires a reason.")
    if context.kind in ("issue", "return", "stocktake") and context.counterpart_job is None:
        raise InvalidInputError("This stock movement requires a counterpart job.")
    movement = StockMovement.objects.create(
        stock=locked,
        quantity_change=change,
        quantity_before=locked.quantity,
        quantity_after=locked.quantity + change,
        unit_cost=locked.unit_cost,
        kind=context.kind,
        reason=context.reason,
        actor=context.actor,
        counterpart_job=context.counterpart_job,
        cost_line=context.cost_line,
        stocktake_line=context.stocktake_line,
        reverses=context.reverses,
    )
    locked.quantity = movement.quantity_after
    locked.inventory_version += 1
    if context.kind == "stocktake" and locked.quantity > 0:
        locked.is_active = True
    locked.save(update_fields=["quantity", "inventory_version", "is_active"])
    stock.quantity = locked.quantity
    stock.inventory_version = locked.inventory_version
    return movement


def inventory_difference(stock: Stock) -> Decimal:
    """Read-only reconciliation; never repair an unexplained difference."""
    total = stock.movements.aggregate(total=Sum("quantity_change", default=Decimal("0")))["total"]
    return stock.quantity - Decimal(total)


@transaction.atomic
def reverse_issue(movement: StockMovement, staff: Staff | None, reason: str) -> StockMovement:
    """Return a complete issue with a linked opposite cost; retries return the first reversal."""
    original = StockMovement.objects.select_for_update().get(pk=movement.pk)
    existing = StockMovement.objects.filter(reverses=original).first()
    if existing is not None:
        return existing
    if original.kind != "issue" or original.cost_line is None or original.counterpart_job is None:
        raise InvalidInputError("Only a job issue can be returned through this action.")
    cost = original.cost_line
    credit = CostLine.objects.create(
        cost_set=cost.cost_set,
        kind="material",
        desc=cost.desc,
        quantity=-cost.quantity,
        unit_cost=cost.unit_cost,
        unit_rev=cost.unit_rev,
        accounting_date=cost.accounting_date,
        managed_by="stock",
    )
    return move_stock(
        original.stock,
        -original.quantity_change,
        MovementContext(
            kind="return",
            reason=reason,
            actor=staff,
            counterpart_job=original.counterpart_job,
            cost_line=credit,
            reverses=original,
        ),
    )
