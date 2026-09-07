"""Draft observations become balanced, immutable stock movements on explicit posting."""

from decimal import Decimal
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Staff
from apps.core.errors import InvalidInputError
from apps.core.models import CompanyDefaults
from apps.job.models import Job
from apps.job.models.costing import CostLine
from apps.job.services.job_service import create_job
from apps.purchasing.models import Stock, Stocktake, StocktakeConfiguration, StocktakeLine
from apps.purchasing.services.allocation_service import ensure_actual_cost_set
from apps.purchasing.services.stock_movement_service import MovementContext, move_stock
from apps.purchasing.stocktake_schemas import StocktakeLineWrite, StocktakeSave


@transaction.atomic
def configure_stocktake(staff: Staff) -> StocktakeConfiguration:
    """Idempotent UI/provisioning setup, serialized on the existing settings row."""
    defaults = CompanyDefaults.objects.select_for_update().get(pk=CompanyDefaults.get_solo().pk)
    existing = StocktakeConfiguration.objects.first()
    if existing is not None:
        return existing
    job = create_job(
        {
            "name": "Stocktake Adjustments",
            "company_id": str(defaults.shop_company_id),
            "estimated_materials": Decimal("0"),
            "estimated_time": Decimal("0"),
        },
        staff,
    )
    return StocktakeConfiguration.objects.create(adjustment_job=job)


def require_workshop_stock(stock: Stock) -> None:
    """Require unassigned physical workshop stock."""
    if stock.job_id != Stock.get_stock_holding_job().id or stock.source == "product_catalog":
        raise InvalidInputError("Count only unassigned workshop stock.")


@transaction.atomic
def create_stocktake(staff: Staff, stock_id: UUID | None) -> Stocktake:
    """Start a dated observation without moving material."""
    configuration = StocktakeConfiguration.objects.first()
    if configuration is None:
        raise InvalidInputError("Set up the stocktake adjustment job before starting a count.")
    count = Stocktake.objects.create(adjustment_job=configuration.adjustment_job, created_by=staff)
    if stock_id is not None:
        stock = Stock.objects.get(pk=stock_id)
        require_workshop_stock(stock)
        StocktakeLine.objects.create(
            stocktake=count,
            stock=stock,
            description=stock.description,
            location=stock.location,
            expected_quantity=stock.quantity,
            expected_version=stock.inventory_version,
            unit_cost=stock.unit_cost,
        )
    return count


def require_draft(count: Stocktake, version: int) -> None:
    """Require an unchanged, unposted draft."""
    if count.posted_at is not None:
        raise InvalidInputError("Posted counts are read-only. Create a linked correction.")
    if count.version != version:
        raise InvalidInputError("This draft changed in another session. Reload before saving.")


def _save_line(count: Stocktake, data: StocktakeLineWrite) -> None:
    stock = None
    if data.stock_id is not None:
        stock = Stock.objects.select_for_update().get(pk=data.stock_id)
        require_workshop_stock(stock)
        if (
            stock.inventory_version != data.expected_version
            or stock.quantity != data.expected_quantity
        ):
            raise InvalidInputError(
                f"{stock.description}: stock changed. Review and recount this line."
            )
        if stock.unit_cost != data.unit_cost:
            raise InvalidInputError(f"{stock.description}: use the recorded unit cost.")
    elif data.expected_quantity != 0 or data.expected_version != 0:
        raise InvalidInputError("Newly found material must start from zero recorded stock.")
    if StocktakeLine.objects.filter(pk=data.id).exclude(stocktake=count).exists():
        raise InvalidInputError("The count line belongs to another stocktake.")
    StocktakeLine.objects.update_or_create(
        pk=data.id,
        stocktake=count,
        defaults={
            "stock": stock,
            "description": data.description,
            "location": data.location,
            "expected_quantity": data.expected_quantity,
            "expected_version": data.expected_version,
            "counted_quantity": data.counted_quantity,
            "unit_cost": data.unit_cost,
            "reason": data.reason,
            "counted_at": timezone.now() if data.counted_quantity is not None else None,
        },
    )


@transaction.atomic
def save_stocktake(count_id: UUID, data: StocktakeSave) -> Stocktake:
    """Save a complete draft while rejecting stale observations."""
    count = Stocktake.objects.select_for_update().get(pk=count_id)
    require_draft(count, data.version)
    ids = [line.id for line in data.lines]
    stock_ids = [line.stock_id for line in data.lines if line.stock_id is not None]
    if len(set(ids)) != len(ids) or len(set(stock_ids)) != len(stock_ids):
        raise InvalidInputError("Count each stock item once.")
    for line in sorted(data.lines, key=lambda row: str(row.stock_id)):
        _save_line(count, line)
    count.lines.exclude(id__in=ids).delete()
    count.version += 1
    count.updated_at = timezone.now()
    count.save(update_fields=["version", "updated_at"])
    return count


def _post_line(line: StocktakeLine, staff: Staff, job: Job) -> None:
    if line.counted_quantity is None:
        return
    difference = line.counted_quantity - line.expected_quantity
    if difference == 0:
        return
    if line.reason is None:
        raise InvalidInputError(f"{line.description}: choose a reason for the difference.")
    if line.stock is None:
        line.stock = Stock.objects.create(
            job=Stock.get_stock_holding_job(),
            description=line.description,
            location=line.location,
            quantity=0,
            unit_cost=line.unit_cost,
            source="manual",
        )
        line.save(update_fields=["stock"])
    cost = CostLine.objects.create(
        cost_set=ensure_actual_cost_set(job, staff),
        kind="material",
        desc=line.description,
        quantity=-difference,
        unit_cost=line.unit_cost,
        unit_rev=Decimal("0"),
        accounting_date=timezone.localdate(),
        managed_by="stocktake",
    )
    move_stock(
        line.stock,
        difference,
        MovementContext(
            kind="stocktake",
            reason=line.reason,
            actor=staff,
            counterpart_job=job,
            cost_line=cost,
            stocktake_line=line,
        ),
    )


@transaction.atomic
def post_stocktake(count_id: UUID, version: int, staff: Staff) -> Stocktake:
    """Post all counted differences atomically and exactly once."""
    count = Stocktake.objects.select_for_update().get(pk=count_id)
    if count.posted_at is not None:
        if count.version != version + 1:
            raise InvalidInputError("This posting request does not match the posted count version.")
        return count
    require_draft(count, version)
    lines = list(count.lines.select_related("stock").order_by("stock_id", "id"))
    counted = [line for line in lines if line.counted_quantity is not None]
    if not counted:
        raise InvalidInputError("Enter at least one physical count before posting.")
    job = Job.objects.select_for_update().get(pk=count.adjustment_job_id)
    if not job.shop_job:
        raise InvalidInputError("The stocktake adjustment job must remain non-billable.")
    for line in counted:
        if line.stock_id is not None:
            stock = Stock.objects.select_for_update().get(pk=line.stock_id)
            require_workshop_stock(stock)
            if (
                stock.inventory_version != line.expected_version
                or stock.quantity != line.expected_quantity
                or stock.unit_cost != line.unit_cost
            ):
                raise InvalidInputError(
                    f"{line.description}: stock changed. Review and recount this line."
                )
            line.stock = stock
        _post_line(line, staff, job)
    count.posted_at = timezone.now()
    count.posted_by = staff
    count.updated_at = count.posted_at
    count.version += 1
    count.save(update_fields=["posted_at", "posted_by", "updated_at", "version"])
    return count


@transaction.atomic
def correct_stocktake(count_id: UUID, staff: Staff) -> Stocktake:
    """Create a linked recount preserving the earlier posting."""
    original = Stocktake.objects.select_for_update().get(pk=count_id)
    if original.posted_at is None:
        raise InvalidInputError("Edit this draft directly; it has not been posted.")
    existing = Stocktake.objects.filter(corrects=original).first()
    if existing is not None:
        return existing
    correction = Stocktake.objects.create(
        adjustment_job=original.adjustment_job,
        created_by=staff,
        corrects=original,
    )
    for line in original.lines.select_related("stock").filter(stock__isnull=False):
        stock = line.stock
        if stock is None:
            raise InvalidInputError("A posted material count is missing its stock identity.")
        StocktakeLine.objects.create(
            stocktake=correction,
            stock=stock,
            description=stock.description,
            location=stock.location,
            expected_quantity=stock.quantity,
            expected_version=stock.inventory_version,
            unit_cost=stock.unit_cost,
        )
    return correction
