"""Authenticated stocktake navigation, drafts, setup and explicit posting."""

from decimal import Decimal
from uuid import UUID

from django.db.models import Prefetch, Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404
from ninja import Query, Router

from apps.accounts.auth import authenticated_staff
from apps.core.auth import CookieJWTAuth
from apps.core.envelope import require_if_match
from apps.core.etag import generate_revision_etag
from apps.purchasing.models import Stock, Stocktake, StocktakeConfiguration, StocktakeLine
from apps.purchasing.services import stocktake_service
from apps.purchasing.stocktake_schemas import (
    StocktakeCreate,
    StocktakeDetail,
    StocktakeLineOut,
    StocktakeList,
    StocktakeSave,
    StocktakeSearch,
    StocktakeSetup,
    StocktakeStockList,
    StocktakeStockOut,
    StocktakeStockSearch,
    StocktakeSummary,
)

router = Router(auth=CookieJWTAuth(), tags=["purchasing"])


def _line_data(line: StocktakeLine, *, posted: bool) -> StocktakeLineOut:
    difference = None
    value = None
    if line.counted_quantity is not None:
        difference = line.counted_quantity - line.expected_quantity
        value = difference * line.unit_cost
    current_quantity = Decimal("0")
    current_version = 0
    if line.stock is not None:
        current_quantity = line.stock.quantity
        current_version = line.stock.inventory_version
    return StocktakeLineOut(
        id=line.id,
        stock_id=line.stock_id,
        description=line.description,
        location=line.location,
        expected_version=line.expected_version,
        expected_quantity=line.expected_quantity,
        counted_quantity=line.counted_quantity,
        counted_at=line.counted_at,
        unit_cost=line.unit_cost,
        reason=line.reason,
        difference=difference,
        value=value,
        current_quantity=current_quantity,
        current_version=current_version,
        stale=not posted
        and (
            current_version != line.expected_version or current_quantity != line.expected_quantity
        ),
    )


def _summary(count: Stocktake) -> StocktakeSummary:
    value = sum(
        (
            (line.counted_quantity - line.expected_quantity) * line.unit_cost
            for line in count.lines.all()
            if line.counted_quantity is not None
        ),
        Decimal("0"),
    )
    return StocktakeSummary(
        id=count.id,
        created_at=count.created_at,
        posted_at=count.posted_at,
        author=count.created_by.get_display_full_name(),
        adjustment_job_id=count.adjustment_job_id,
        discrepancy_value=value,
        corrects_id=count.corrects_id,
    )


def _detail(count_id: UUID, response: HttpResponse) -> StocktakeDetail:
    count = get_object_or_404(
        Stocktake.objects.select_related("created_by").prefetch_related(
            Prefetch(
                "lines", queryset=StocktakeLine.objects.select_related("stock").order_by("id")
            ),
        ),
        pk=count_id,
    )
    response["ETag"] = generate_revision_etag("stocktake", count.id, count.version)
    response["Cache-Control"] = "no-store"
    return StocktakeDetail(
        **_summary(count).model_dump(),
        lines=[_line_data(line, posted=count.posted_at is not None) for line in count.lines.all()],
    )


@router.get("/setup/", response=StocktakeSetup, operation_id="stocktake_setup_retrieve")
def setup_retrieve(request: HttpRequest) -> StocktakeSetup:
    """Read setup without creating a job or configuration row."""
    authenticated_staff(request)
    configuration = StocktakeConfiguration.objects.filter(
        pk=StocktakeConfiguration.singleton_instance_id
    ).first()
    return StocktakeSetup(
        adjustment_job_id=configuration.adjustment_job_id if configuration is not None else None,
    )


@router.post("/setup/", response=StocktakeSetup, operation_id="stocktake_setup_create")
def setup_create(request: HttpRequest) -> StocktakeSetup:
    """Create the non-billable counterpart once through the supported workflow."""
    configuration = stocktake_service.configure_stocktake(authenticated_staff(request))
    return StocktakeSetup(adjustment_job_id=configuration.adjustment_job_id)


@router.get("/stock/", response=StocktakeStockList, operation_id="stocktake_stock_list")
def stock_list(request: HttpRequest, params: Query[StocktakeStockSearch]) -> StocktakeStockList:
    """Search active physical workshop stock, including zero balances."""
    authenticated_staff(request)
    rows = Stock.objects.filter(job=Stock.get_stock_holding_job(), is_active=True).exclude(
        source="product_catalog"
    )
    if params.stock_ids:
        rows = rows.filter(id__in=params.stock_ids)
    if params.q:
        rows = rows.filter(Q(description__icontains=params.q) | Q(item_code__icontains=params.q))
    if params.location:
        rows = rows.filter(location__icontains=params.location)
    offset = (params.page - 1) * params.page_size
    return StocktakeStockList(
        count=rows.count(),
        results=[
            StocktakeStockOut.model_validate(stock)
            for stock in rows.order_by("description", "id")[offset : offset + params.page_size]
        ],
    )


@router.get("/", response=StocktakeList, operation_id="stocktake_list")
def count_list(request: HttpRequest, params: Query[StocktakeSearch]) -> StocktakeList:
    """List counts with bounded paging and their net inventory value differences."""
    authenticated_staff(request)
    rows = (
        Stocktake.objects.select_related("created_by")
        .prefetch_related("lines")
        .order_by("-created_at", "id")
    )
    offset = (params.page - 1) * params.page_size
    return StocktakeList(
        count=rows.count(),
        results=[_summary(count) for count in rows[offset : offset + params.page_size]],
    )


@router.post("/", response=StocktakeDetail, operation_id="stocktake_create")
def count_create(
    request: HttpRequest, response: HttpResponse, payload: StocktakeCreate
) -> StocktakeDetail:
    """Start a count, optionally preselecting a stock row for a spot correction."""
    if payload.stock_id is not None:
        get_object_or_404(Stock, pk=payload.stock_id)
    count = stocktake_service.create_stocktake(authenticated_staff(request), payload.stock_id)
    return _detail(count.id, response)


@router.get("/{uuid:id}/", response=StocktakeDetail, operation_id="stocktake_retrieve")
def count_retrieve(request: HttpRequest, response: HttpResponse, id: UUID) -> StocktakeDetail:
    """Read a draft or immutable posted count and its current stock versions."""
    authenticated_staff(request)
    return _detail(id, response)


@router.put("/{uuid:id}/", response=StocktakeDetail, operation_id="stocktake_update")
def count_update(
    request: HttpRequest, response: HttpResponse, id: UUID, payload: StocktakeSave
) -> StocktakeDetail:
    """Save all draft observations atomically with a draft version precondition."""
    authenticated_staff(request)
    get_object_or_404(Stocktake, pk=id)
    stocktake_service.save_stocktake(id, payload, if_match=require_if_match(request))
    return _detail(id, response)


@router.post("/{uuid:id}/post/", response=StocktakeDetail, operation_id="stocktake_post")
def count_post(request: HttpRequest, response: HttpResponse, id: UUID) -> StocktakeDetail:
    """Post the reviewed count exactly once."""
    get_object_or_404(Stocktake, pk=id)
    stocktake_service.post_stocktake(id, require_if_match(request), authenticated_staff(request))
    return _detail(id, response)


@router.post("/{uuid:id}/correct/", response=StocktakeDetail, operation_id="stocktake_correct")
def count_correct(request: HttpRequest, response: HttpResponse, id: UUID) -> StocktakeDetail:
    """Start a linked recount without erasing the original observation."""
    get_object_or_404(Stocktake, pk=id)
    return _detail(
        stocktake_service.correct_stocktake(
            id, authenticated_staff(request), if_match=require_if_match(request)
        ).id,
        response,
    )
