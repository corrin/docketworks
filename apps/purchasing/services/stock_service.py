import logging
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from apps.job.models import CostLine, CostSet, Job
from apps.purchasing.models import Stock
from apps.workflow.models import CompanyDefaults

logger = logging.getLogger(__name__)


@transaction.atomic
def merge_stock_into(source_stock_id: UUID, target_stock_id: UUID) -> None:
    """
    Merge source stock into target, moving all references then deleting source.

    Moves:
    - child_stock_splits (source_parent_stock FK)
    - CostLine ext_refs['stock_id'] references (JSON update)

    Then deletes the source stock.
    """
    source_str = str(source_stock_id)
    target_str = str(target_stock_id)

    # 1. Move child stock splits (FK)
    Stock.objects.filter(source_parent_stock_id=source_stock_id).update(
        source_parent_stock_id=target_stock_id
    )

    # 2. Update CostLine ext_refs JSON where stock_id matches source
    for cl in CostLine.objects.filter(ext_refs__stock_id=source_str):
        cl.ext_refs["stock_id"] = target_str
        cl.save(update_fields=["ext_refs"])

    # 3. Delete the source stock
    Stock.objects.filter(id=source_stock_id).delete()

    logger.info(f"Merged stock {source_stock_id} into {target_stock_id}")


def consume_stock(
    item: Stock,
    job: Job,
    qty: Decimal,
    user: Any,
    unit_cost: Optional[Decimal] = None,
    unit_rev: Optional[Decimal] = None,
    line: Optional[CostLine] = None,
) -> CostLine:
    if qty <= 0:
        raise ValueError("Quantity must be positive")

    with transaction.atomic():
        # Reload with row-level lock to avoid race conditions
        item = Stock.objects.select_for_update().get(id=item.id)

        original_quantity = item.quantity
        item.quantity -= qty

        # Log warnings for negative stock but allow it
        if item.quantity < 0:
            logger.warning(
                f"Stock item {item.id} ({item.description}) went negative: {original_quantity} -> {item.quantity} (consumed {qty})"
            )
        elif item.quantity == 0:
            logger.info(
                f"Stock item {item.id} ({item.description}) fully consumed: {original_quantity} -> 0 (consumed {qty})"
            )

        # Save the new quantity (negative quantities are allowed)
        item.save(update_fields=["quantity"])

        # If no unit cost or revenue is provided, this means the staff didn't override the default values from stock
        if unit_cost is None:
            unit_cost = item.unit_cost

        # Shop jobs don't bill customers, so revenue must be zero
        if job.shop_job:
            unit_rev = Decimal("0.00")
        elif unit_rev is None:
            materials_markup = CompanyDefaults.get_solo().materials_markup
            unit_rev = item.unit_cost * (1 + materials_markup)

        # Ensure job has an actual cost set
        if not job.latest_actual:
            actual_cost_set = CostSet.objects.create(
                job=job, kind="actual", rev=1, summary={"cost": 0, "rev": 0, "hours": 0}
            )
            job.latest_actual = actual_cost_set
            job.save(staff=user, update_fields=["latest_actual"])
            logger.info(f"Created missing actual CostSet for job {job.id}")

        cost_set = job.latest_actual

        if not line:
            cost_line = CostLine.objects.create(
                cost_set=cost_set,
                kind="material",
                desc=item.description,
                quantity=qty,
                unit_cost=unit_cost,
                unit_rev=unit_rev,
                accounting_date=timezone.now().date(),
                ext_refs={"stock_id": str(item.id)},
                meta={
                    "consumed_by": (
                        str(getattr(user, "id", None))
                        if getattr(user, "id", None)
                        else None
                    )
                },
            )
            logger.info(
                "Consumed %s of stock %s for job %s and created new line with id: %s",
                qty,
                item.id,
                job.id,
                cost_line.id,
            )
            return cost_line

        line.approved = True
        line.quantity = qty
        line.desc = item.description
        line.unit_cost = unit_cost
        line.unit_rev = unit_rev
        line.accounting_date = timezone.now().date()
        line.ext_refs = {"stock_id": str(item.id)}
        line.meta = {
            "consumed_by": (
                str(getattr(user, "id", None)) if getattr(user, "id", None) else None
            )
        }

        line.save(
            update_fields=[
                "approved",
                "desc",
                "unit_cost",
                "unit_rev",
                "accounting_date",
                "ext_refs",
                "meta",
            ]
        )
    return line
