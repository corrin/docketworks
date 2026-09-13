"""Read movement evidence and return issued material without deleting job charges."""

from datetime import datetime
from uuid import UUID

from django.db.models import QuerySet
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from ninja import Router

from apps.accounts.auth import authenticated_staff
from apps.core.auth import CookieJWTAuth
from apps.core.pagination import paginate
from apps.core.schemas import Quantity, ResponseSchema
from apps.purchasing.models import StockMovement, StockMovementKind
from apps.purchasing.services.stock_movement_service import is_returnable_issue, reverse_issue

router = Router(auth=CookieJWTAuth(), tags=["purchasing"])


class StockMovementOut(ResponseSchema):
    """A movement and its human-readable counterpart."""

    id: UUID
    stock_id: UUID
    description: str
    quantity_before: Quantity
    quantity_after: Quantity
    quantity_change: Quantity
    unit_cost: Quantity
    kind: StockMovementKind
    reason: str
    recorded_at: datetime
    actor: str | None
    counterpart_job_id: UUID | None
    counterpart_name: str
    can_return: bool


class StockMovementPage(ResponseSchema):
    """Bound movement responses using the shared pagination envelope."""

    results: list[StockMovementOut]
    count: int
    page: int
    page_size: int
    total_pages: int


def movement_data(movement: StockMovement, reversed_ids: set[UUID]) -> StockMovementOut:
    """Project immutable evidence without depending on current stock balances."""
    counterpart = movement.get_kind_display()
    if movement.counterpart_job is not None:
        counterpart = movement.counterpart_job.name
    return StockMovementOut(
        id=movement.id,
        stock_id=movement.stock_id,
        description=movement.stock.description,
        quantity_before=movement.quantity_before,
        quantity_after=movement.quantity_after,
        quantity_change=movement.quantity_change,
        unit_cost=movement.unit_cost,
        kind=StockMovementKind(movement.kind),
        reason=movement.reason,
        recorded_at=movement.recorded_at,
        actor=movement.actor.get_display_full_name() if movement.actor is not None else None,
        counterpart_job_id=movement.counterpart_job_id,
        counterpart_name=counterpart,
        can_return=is_returnable_issue(movement) and movement.id not in reversed_ids,
    )


@router.get(
    "/stock/{uuid:id}/movements/",
    response=StockMovementPage,
    operation_id="stock_movements_list",
)
def stock_history(
    request: HttpRequest, id: UUID, page: int = 1, page_size: int = 50
) -> StockMovementPage:
    """Read a bounded page of a stock identity's movement history."""
    authenticated_staff(request)
    return _movement_page(StockMovement.objects.filter(stock_id=id), page, page_size)


@router.get(
    "/stocktakes/{uuid:id}/movements/",
    response=StockMovementPage,
    operation_id="stocktake_movements_list",
)
def count_history(
    request: HttpRequest, id: UUID, page: int = 1, page_size: int = 50
) -> StockMovementPage:
    """Read a bounded page of a count's posted differences."""
    authenticated_staff(request)
    return _movement_page(
        StockMovement.objects.filter(stocktake_line__stocktake_id=id), page, page_size
    )


def _movement_page(
    movements: QuerySet[StockMovement], page: int, page_size: int
) -> StockMovementPage:
    result = paginate(
        movements.select_related("stock", "actor", "counterpart_job", "cost_line").order_by(
            "recorded_at", "id"
        ),
        page=page,
        page_size=page_size,
    )
    reversed_ids = set(
        StockMovement.objects.filter(reverses__in=result.rows).values_list("reverses_id", flat=True)
    )
    return StockMovementPage(
        count=result.count,
        page=result.page,
        page_size=result.page_size,
        total_pages=result.total_pages,
        results=[movement_data(movement, reversed_ids) for movement in result.rows],
    )


@router.post(
    "/stock-movements/{uuid:id}/return/",
    response=StockMovementOut,
    operation_id="stock_movement_return",
)
def return_material(request: HttpRequest, id: UUID) -> StockMovementOut:
    """Return an issue and credit its original job once."""
    movement = get_object_or_404(StockMovement, pk=id)
    returned = reverse_issue(
        movement, authenticated_staff(request), "Unused material returned to workshop"
    )
    return movement_data(returned, set())


@router.get(
    "/cost-lines/{uuid:id}/movement/",
    response=StockMovementOut,
    operation_id="cost_line_stock_movement_retrieve",
)
def cost_movement(request: HttpRequest, id: UUID) -> StockMovementOut:
    """Locate the owning movement without decoding costing's historical JSON references."""
    authenticated_staff(request)
    movement = get_object_or_404(
        StockMovement.objects.select_related("stock", "actor", "counterpart_job", "cost_line"),
        cost_line_id=id,
    )
    reversed_ids = set(
        StockMovement.objects.filter(reverses=movement).values_list("reverses_id", flat=True)
    )
    return movement_data(movement, {pk for pk in reversed_ids if pk is not None})
