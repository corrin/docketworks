"""Celery tasks for purchasing stock metadata parsing."""

import logging
from typing import Protocol, cast
from uuid import UUID

from celery import shared_task
from django.db import close_old_connections, connection, transaction
from django.db.models import Q

from apps.purchasing.models import Stock
from apps.quoting.services.stock_parser import auto_parse_stock_item
from apps.workflow.exceptions import AlreadyLoggedException
from apps.workflow.services.error_persistence import persist_app_error

logger = logging.getLogger("apps.purchasing.tasks")


class ParseStockItemTask(Protocol):
    def __call__(self, stock_id: str, force: bool = False) -> None: ...

    def delay(self, stock_id: str, *, force: bool = False) -> object: ...


class ParseUnparsedStockItemsTask(Protocol):
    def __call__(self, limit: int = 50) -> None: ...

    def delay(self, limit: int = 50) -> object: ...


def _incomplete_stock_metadata_query() -> Q:
    return (
        Q(alloy__isnull=True)
        | Q(alloy="")
        | Q(specifics__isnull=True)
        | Q(specifics="")
        | Q(metal_type__isnull=True)
        | Q(metal_type="")
        | Q(metal_type="unspecified")
    )


def stock_metadata_incomplete(stock: Stock) -> bool:
    """Return True when stock is missing metadata the parser can infer."""
    return (
        not stock.alloy
        or not stock.specifics
        or not stock.metal_type
        or stock.metal_type == "unspecified"
    )


def stock_metadata_parse_eligible(stock: Stock, *, force: bool = False) -> bool:
    """Return True when stock should be queued for one automatic parser attempt."""
    if force:
        return True
    if stock.parsed_at:
        return False
    if stock.parser_attempted_at:
        return False
    return stock_metadata_incomplete(stock)


def enqueue_stock_metadata_parse(stock_id: UUID | str, *, force: bool = False) -> None:
    """Queue metadata parsing after the surrounding DB transaction commits."""

    def _enqueue() -> None:
        parse_stock_item_task.delay(str(stock_id), force=force)

    transaction.on_commit(_enqueue)


def _parse_stock_item_task(stock_id: str, force: bool = False) -> None:
    """Parse one active stock row's missing metadata."""
    try:
        if connection.in_atomic_block:
            pass  # Inline task execution in tests owns the transaction connection.
        else:
            close_old_connections()
        stock = Stock.objects.filter(id=stock_id, is_active=True).first()

        if stock is None:
            logger.info(
                "Skipping stock metadata parse for inactive/missing stock %s",
                stock_id,
            )
            return

        if stock.parsed_at and not force:
            logger.info("Skipping already parsed stock %s", stock_id)
            return

        if stock.parser_attempted_at and not force:
            logger.info("Skipping already attempted stock %s", stock_id)
            return

        if not force and not stock_metadata_parse_eligible(stock):
            logger.info("Skipping complete stock metadata for %s", stock_id)
            return
        else:
            auto_parse_stock_item(stock, force=force)
    except AlreadyLoggedException:
        raise
    except Exception as exc:
        logger.error(
            "Error parsing stock metadata for %s: %s",
            stock_id,
            exc,
            exc_info=True,
        )
        app_error = persist_app_error(exc)
        raise AlreadyLoggedException(exc, app_error.id) from exc


parse_stock_item_task = cast(
    ParseStockItemTask,
    shared_task(name="apps.purchasing.tasks.parse_stock_item_task")(
        _parse_stock_item_task
    ),
)


def _parse_unparsed_stock_items_task(limit: int = 50) -> None:
    """Queue a bounded catch-up batch for active stock with missing metadata."""
    try:
        if connection.in_atomic_block:
            pass  # Inline task execution in tests owns the transaction connection.
        else:
            close_old_connections()
        limit = max(1, min(int(limit), 500))
        stock_ids: list[UUID] = list(
            Stock.objects.filter(
                is_active=True,
                parsed_at__isnull=True,
                parser_attempted_at__isnull=True,
            )
            .filter(_incomplete_stock_metadata_query())
            .order_by("date", "id")
            .values_list("id", flat=True)[:limit]
        )
        for stock_id in stock_ids:
            parse_stock_item_task.delay(str(stock_id))
        logger.info("Queued %s stock metadata parse tasks.", len(stock_ids))
    except AlreadyLoggedException:
        raise
    except Exception as exc:
        logger.error(
            "Error queueing stock metadata parse batch: %s",
            exc,
            exc_info=True,
        )
        app_error = persist_app_error(exc)
        raise AlreadyLoggedException(exc, app_error.id) from exc


parse_unparsed_stock_items_task = cast(
    ParseUnparsedStockItemsTask,
    shared_task(name="apps.purchasing.tasks.parse_unparsed_stock_items_task")(
        _parse_unparsed_stock_items_task
    ),
)
