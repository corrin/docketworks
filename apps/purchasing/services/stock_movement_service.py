"""The single writer of inventory balances and their durable counterparts."""

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, TypedDict

from django.db import connection, transaction
from django.db.models import F, QuerySet, Sum
from django.utils import timezone

from apps.accounts.models import Staff
from apps.core.errors import InvalidInputError
from apps.job.models import Job
from apps.job.models.costing import CostLine, lock_costing_jobs
from apps.purchasing.models import Stock, StockMovement, StockMovementKind, StocktakeLine

if TYPE_CHECKING:
    from django_stubs_ext import WithAnnotations


class InventoryBalance(TypedDict):
    """The ledger projection alongside a stock row's stored balance."""

    ledger_quantity: Decimal


def inventory_balances() -> QuerySet["WithAnnotations[Stock, InventoryBalance]"]:
    """Project every identity, including empty and retired identities, in one query."""
    return Stock.objects.annotate(
        ledger_quantity=Sum("movements__quantity_change", default=Decimal("0"))
    )


@dataclass(frozen=True)
class MovementContext:
    """Provenance supplied by the workflow that owns the movement."""

    kind: StockMovementKind
    reason: str
    actor: Staff | None = None
    counterpart_job: Job | None = None
    cost_line: CostLine | None = None
    stocktake_line: StocktakeLine | None = None
    reverses: StockMovement | None = None


@transaction.atomic
def move_stock(stock: Stock, change: Decimal, context: MovementContext) -> StockMovement:
    """Lock, record and project one movement; negative inventory remains permitted."""
    if context.kind in (
        StockMovementKind.OPENING,
        StockMovementKind.JOB_OPENING,
        StockMovementKind.RECEIPT_OPENING,
    ):
        raise InvalidInputError("Opening observations belong to the inventory cutover migration.")
    locked = Stock.objects.select_for_update().get(pk=stock.pk)
    if change != change.quantize(Decimal("0.001")):
        raise InvalidInputError("Stock quantities support at most three decimal places.")
    if not context.reason.strip():
        raise InvalidInputError("A stock movement requires a reason.")
    if context.kind in ("issue", "return", "stocktake") and context.counterpart_job is None:
        raise InvalidInputError("This stock movement requires a counterpart job.")
    if context.kind in ("issue", "return", "stocktake"):
        cost = context.cost_line
        if cost is None or cost.quantity != -change:
            raise InvalidInputError("The movement requires its matching job cost quantity.")
        if cost.cost_set.job != context.counterpart_job or cost.cost_set.kind != "actual":
            raise InvalidInputError(
                "The movement cost must belong to its counterpart job's actuals."
            )
    movement = StockMovement.objects.create(
        stock=locked,
        quantity_change=change,
        quantity_before=locked.quantity,
        quantity_after=locked.quantity + change,
        unit_cost=context.cost_line.unit_cost
        if context.cost_line is not None
        else locked.unit_cost,
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
    if locked.quantity != 0:
        locked.is_active = True
    locked.save(update_fields=["quantity", "inventory_version", "is_active"])
    stock.quantity = locked.quantity
    stock.inventory_version = locked.inventory_version
    stock.is_active = locked.is_active
    return movement


def inventory_difference(stock: Stock) -> Decimal:
    """Read-only reconciliation; never repair an unexplained difference."""
    return stock.quantity - inventory_balances().get(pk=stock.pk).ledger_quantity


_LEDGER_AUDITS = {
    "Movement continuity": """
        WITH ordered AS (
            SELECT id, quantity_before,
                   lag(quantity_after, 1, 0) OVER (
                       PARTITION BY stock_id ORDER BY recorded_at, id
                   ) AS preceding_quantity
            FROM purchasing_stockmovement
        )
        SELECT id::text FROM ordered WHERE quantity_before <> preceding_quantity
    """,
    "Job cost counterparts": """
        SELECT m.id::text FROM purchasing_stockmovement m
        LEFT JOIN job_costline c ON c.id = m.cost_line_id
        LEFT JOIN job_costset cs ON cs.id = c.cost_set_id
        WHERE m.kind IN ('issue', 'return', 'job_opening', 'stocktake')
          AND (c.id IS NULL OR cs.kind <> 'actual' OR c.kind <> 'material'
               OR NOT c.approved OR cs.job_id IS DISTINCT FROM m.counterpart_job_id
               OR c.unit_cost IS DISTINCT FROM m.unit_cost
               OR c.managed_by IS DISTINCT FROM
                   CASE WHEN m.kind = 'stocktake' THEN 'stocktake' ELSE 'stock' END
               OR (m.kind <> 'job_opening' AND c.quantity <> -m.quantity_change)
               OR (m.kind = 'job_opening' AND (c.quantity <= 0 OR m.quantity_change <> 0)))
    """,
    "Unlinked inventory costs": """
        SELECT c.id::text FROM job_costline c
        WHERE c.managed_by IN ('stock', 'stocktake')
          AND NOT EXISTS (
              SELECT 1 FROM purchasing_stockmovement m WHERE m.cost_line_id = c.id
                AND m.kind IN ('issue', 'return', 'job_opening', 'stocktake')
          )
    """,
    "Reversal evidence": """
        SELECT m.id::text FROM purchasing_stockmovement m
        LEFT JOIN purchasing_stockmovement original ON original.id = m.reverses_id
        LEFT JOIN job_costline charge ON charge.id = original.cost_line_id
        LEFT JOIN job_costline credit ON credit.id = m.cost_line_id
        WHERE m.kind IN ('return', 'receipt_reversal')
          AND (original.id IS NULL OR original.stock_id <> m.stock_id
               OR m.unit_cost IS DISTINCT FROM original.unit_cost
               OR (m.kind = 'return' AND (
                   original.kind NOT IN ('issue', 'job_opening')
                   OR m.counterpart_job_id IS DISTINCT FROM original.counterpart_job_id
                   OR charge.id IS NULL OR credit.id IS NULL
                   OR m.quantity_change <> charge.quantity
                   OR credit.unit_cost IS DISTINCT FROM charge.unit_cost
                   OR credit.unit_rev IS DISTINCT FROM charge.unit_rev))
               OR (m.kind = 'receipt_reversal' AND (
                   original.kind NOT IN ('receipt', 'receipt_opening')
                   OR m.quantity_change IS DISTINCT FROM -CASE
                       WHEN original.kind = 'receipt_opening' THEN original.opening_quantity
                       ELSE original.quantity_change END)))
    """,
    "Stocktake posting evidence": """
        SELECT m.id::text FROM purchasing_stockmovement m
        LEFT JOIN purchasing_stocktakeline l ON l.id = m.stocktake_line_id
        LEFT JOIN purchasing_stocktake t ON t.id = l.stocktake_id
        WHERE m.kind = 'stocktake'
          AND (l.id IS NULL OR t.posted_at IS NULL OR l.stock_id IS DISTINCT FROM m.stock_id
               OR l.counted_quantity IS NULL
               OR m.quantity_change <> l.counted_quantity - l.expected_quantity
               OR m.unit_cost <> l.unit_cost)
        UNION ALL
        SELECT l.id::text FROM purchasing_stocktakeline l
        JOIN purchasing_stocktake t ON t.id = l.stocktake_id
        WHERE t.posted_at IS NOT NULL AND l.counted_quantity <> l.expected_quantity
          AND NOT EXISTS (
              SELECT 1 FROM purchasing_stockmovement m WHERE m.stocktake_line_id = l.id
          )
    """,
    "Supplier receipt totals": """
        WITH pending_lines AS (
            SELECT s.source_purchase_order_line_id AS id FROM purchasing_stock s
            WHERE s.source = 'purchase_order' AND NOT EXISTS (
                SELECT 1 FROM purchasing_stockmovement m WHERE m.stock_id = s.id
                  AND m.kind IN ('receipt', 'receipt_opening')
            )
            UNION
            SELECT pl.id FROM purchasing_purchaseorderline pl
            JOIN job_costline c ON c.ext_refs->>'purchase_order_line_id' = pl.id::text
            JOIN job_costset cs ON cs.id = c.cost_set_id
            WHERE cs.kind = 'actual' AND c.kind = 'material'
              AND c.ext_refs ? 'purchase_order_id' AND NOT EXISTS (
                  SELECT 1 FROM purchasing_stockmovement m WHERE m.cost_line_id = c.id
              )
        ), receipts AS (
            SELECT s.source_purchase_order_line_id AS id,
                   sum(CASE WHEN m.kind = 'receipt_opening' THEN m.opening_quantity
                            ELSE m.quantity_change END) AS quantity
            FROM purchasing_stock s JOIN purchasing_stockmovement m ON m.stock_id = s.id
            WHERE m.kind IN ('receipt', 'receipt_opening', 'receipt_reversal')
            GROUP BY s.source_purchase_order_line_id
        )
        SELECT pl.id::text FROM purchasing_purchaseorderline pl
        LEFT JOIN receipts r ON r.id = pl.id
        LEFT JOIN purchasing_legacyreceiptadjustment legacy
          ON legacy.purchase_order_line_id = pl.id
        WHERE pl.received_quantity <> coalesce(r.quantity, 0) + coalesce(legacy.quantity, 0)
          AND NOT EXISTS (SELECT 1 FROM pending_lines p WHERE p.id = pl.id)
    """,
}


def inventory_audit_findings() -> dict[str, list[str]]:
    """Read discrepancies across the ledger; never manufacture missing evidence.

    Receipt totals with explicit pending opening candidates become auditable
    after the cutover. All already-posted movement and cost evidence is checked
    both before and after it.
    """
    findings = {
        "Stock balances": [
            f"{stock.id}: recorded={stock.quantity}, ledger={stock.ledger_quantity}"
            for stock in inventory_balances().exclude(quantity=F("ledger_quantity")).order_by("id")
        ]
    }
    with connection.cursor() as cursor:
        for label, query in _LEDGER_AUDITS.items():
            cursor.execute(query)
            findings[label] = sorted(str(row[0]) for row in cursor.fetchall())
    return {label: rows for label, rows in findings.items() if rows}


def receipt_quantity(movement: StockMovement) -> Decimal:
    """Read the supplied quantity from either a posting or an explicit cutover observation."""
    if movement.kind == "receipt":
        return movement.quantity_change
    if movement.kind != "receipt_opening" or movement.opening_quantity is None:
        raise InvalidInputError("This movement is not receipt evidence.")
    return movement.opening_quantity


def is_returnable_issue(movement: StockMovement) -> bool:
    """Identify a job position without resolving mutation prerequisites on a GET."""
    return movement.kind in ("issue", "job_opening")


def returnable_issue_cost(movement: StockMovement) -> CostLine:
    """Validate the immutable cost evidence at the return command boundary."""
    if not is_returnable_issue(movement):
        raise InvalidInputError("Only a job issue can be returned through this action.")
    if movement.cost_line is None or movement.counterpart_job is None:
        raise InvalidInputError("The issued material has incomplete movement evidence.")
    cost = movement.cost_line
    if cost.quantity <= 0:
        raise InvalidInputError("A return requires a positive movement job quantity.")
    if movement.kind == "issue" and movement.quantity_change != -cost.quantity:
        raise InvalidInputError("The issue quantity does not match its movement job cost.")
    if movement.kind == "job_opening" and movement.quantity_change != 0:
        raise InvalidInputError("A job opening must not change the workshop balance.")
    return cost


@transaction.atomic
def reverse_issue(movement: StockMovement, staff: Staff, reason: str) -> StockMovement:
    """Return a complete issue with a linked opposite cost; retries return the first reversal."""
    if movement.counterpart_job_id is not None:
        lock_costing_jobs([movement.counterpart_job_id])
    original = StockMovement.objects.select_for_update().get(pk=movement.pk)
    existing = StockMovement.objects.filter(reverses=original).first()
    if existing is not None:
        return existing
    cost = returnable_issue_cost(original)
    credit = CostLine.objects.create(
        cost_set=cost.cost_set,
        kind="material",
        desc=cost.desc,
        quantity=-cost.quantity,
        unit_cost=cost.unit_cost,
        unit_rev=cost.unit_rev,
        accounting_date=timezone.localdate(),
        managed_by="stock",
    )
    return move_stock(
        original.stock,
        cost.quantity,
        MovementContext(
            kind=StockMovementKind.RETURN,
            reason=reason,
            actor=staff,
            counterpart_job=original.counterpart_job,
            cost_line=credit,
            reverses=original,
        ),
    )
