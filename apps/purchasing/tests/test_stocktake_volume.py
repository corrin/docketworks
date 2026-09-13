"""Whole-count posting at the recorded production inventory size."""

from collections.abc import Callable
from cProfile import Profile
from decimal import Decimal
from time import perf_counter
from types import CodeType

import pytest
from django.db import connection, reset_queries
from django.db.models import Sum
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.accounts.models import Staff
from apps.core.etag import generate_revision_etag
from apps.job.models import CostLine, Job
from apps.purchasing.models import Stock, StockMovement, StockMovementKind, StocktakeLine
from apps.purchasing.services.stocktake_service import (
    configure_stocktake,
    create_stocktake,
    post_stocktake,
)

pytestmark = pytest.mark.committed_db


@pytest.mark.parametrize("history_size", [0, 1000])
@pytest.mark.parametrize("differences", [0, 20, 70])
def test_count_posts_all_differences_once_at_inventory_volume(
    office_staff: Staff,
    stock_holding_job: Job,
    history_size: int,
    differences: int,
    record_property: Callable[[str, object], None],
) -> None:
    """Large counts must preserve all postings and retries as adjustment history grows."""
    configuration = configure_stocktake(office_staff)
    cost_set = configuration.adjustment_job.latest_actual
    # GPT: historical manual adjustments are unrelated starting evidence; the
    # stocktake posting below crosses the complete service/commit path.
    CostLine.objects.bulk_create(
        [
            CostLine(
                cost_set=cost_set,
                kind="adjust",
                desc="Historical adjustment",
                quantity=Decimal("1"),
                unit_cost=Decimal("1"),
                unit_rev=Decimal("0"),
                accounting_date=timezone.localdate(),
                meta={"comments": "Historical adjustment"},
            )
            for _ in range(history_size)
        ]
    )
    cost_set.recalculate_summary()
    stocks = Stock.objects.bulk_create(
        [
            Stock(
                job=stock_holding_job,
                description=f"Counted material {index}",
                quantity=Decimal("1"),
                unit_cost=Decimal("1"),
                source="manual",
                date=timezone.now(),
            )
            for index in range(700)
        ]
    )
    StockMovement.objects.bulk_create(
        [
            StockMovement(
                stock=stock,
                quantity_change=Decimal("1"),
                quantity_before=Decimal("0"),
                quantity_after=Decimal("1"),
                unit_cost=Decimal("1"),
                kind=StockMovementKind.OPENING,
                reason="Fixture cutover opening",
            )
            for stock in stocks
        ]
    )
    count = create_stocktake(office_staff, None)
    StocktakeLine.objects.bulk_create(
        [
            StocktakeLine(
                stocktake=count,
                stock=stock,
                description=stock.description,
                expected_quantity=Decimal("1"),
                expected_version=0,
                counted_quantity=Decimal("2") if index < differences else Decimal("1"),
                unit_cost=Decimal("1"),
                reason="Physical count",
                counted_at=timezone.now(),
            )
            for index, stock in enumerate(stocks)
        ]
    )
    version = generate_revision_etag("stocktake", count.id, count.version)
    profiler = Profile()
    reset_queries()
    with CaptureQueriesContext(connection) as queries:
        started = perf_counter()
        profiler.enable()
        posted = post_stocktake(count.id, version, office_staff)
        profiler.disable()
        elapsed = perf_counter() - started
    maintenance = sum(
        entry.totaltime
        for entry in profiler.getstats()
        if isinstance(entry.code, CodeType) and entry.code.co_name == "_record_line_change"
    )
    record_property("history_size", history_size)
    record_property("differences", differences)
    record_property("post_seconds", round(elapsed, 4))
    record_property("summary_seconds", round(maintenance, 4))
    record_property("queries", len(queries))
    assert posted.posted_at is not None
    assert StockMovement.objects.filter(kind="stocktake").count() == differences
    assert (
        Stock.objects.filter(pk__in=[stock.id for stock in stocks]).aggregate(Sum("quantity"))[
            "quantity__sum"
        ]
        == 700 + differences
    )
    cost_set.refresh_from_db()
    assert cost_set.summary["cost"] == history_size - differences
    assert cost_set.summary_is_current()
    post_stocktake(count.id, version, office_staff)
    assert StockMovement.objects.filter(kind="stocktake").count() == differences
