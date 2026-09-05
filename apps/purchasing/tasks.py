"""Celery tasks for stock metadata parsing.

CLOSES THE STOCK METADATA PARSER SEAM. Every stock write enqueues
``parse_stock_item_task``, which hands the row to
``apps.quoting.services.stock_parser.auto_parse_stock_item`` to fill in whatever
``metal_type``/``alloy``/``specifics`` the caller left blank. The seam was open
because the quoting-side parser did not exist yet; it does now, and the three
write sites (``stock_service.create_stock``, ``stock_service.update_stock`` and
``allocation_service.create_stock_from_allocation``) call
``enqueue_stock_metadata_parse``.

Task names are part of the operational contract.

Eligibility is the core design: the parser costs an LLM call
per row, so a row gets exactly ONE automatic attempt. ``parser_attempted_at``
records that attempt whether or not it yielded anything, and both this task and
the catch-up batch skip rows that carry it. That is why
``auto_parse_stock_item`` stamps the attempt even when the model returns
nothing, and does NOT stamp it when the call raises — an outage must not
permanently disqualify a row.

``enqueue_stock_metadata_parse`` queues on ``transaction.on_commit`` so a worker
can never pick up a stock id that the caller's transaction later rolls back.

PHASE 4 SEAM: Xero item sync must also enqueue on creation or change. The Xero
app currently has no stock transform to attach that integration to.
"""

import logging
from uuid import UUID

from celery import current_app, shared_task
from django.db import close_old_connections, connection, transaction
from django.db.models import Q

from apps.core.errors import AppErrorContext, persist_app_error
from apps.purchasing.models import PurchaseOrder, Stock
from apps.quoting.services.stock_parser import auto_parse_stock_item

logger = logging.getLogger("apps.purchasing.tasks")

#: The Xero-side push, addressed by name across the layer boundary.
PUSH_PURCHASE_ORDER_TASK = "apps.xero.tasks.push_purchase_order_to_xero"


MAX_CATCH_UP_BATCH = 500


def _incomplete_metadata_query() -> Q:
    """Rows missing at least one field the parser can infer."""
    return Q(alloy__isnull=True) | Q(specifics__isnull=True) | Q(metal_type__isnull=True)


def stock_metadata_incomplete(stock: Stock) -> bool:
    """Return True when the row is missing metadata the parser could infer."""
    return not stock.alloy or not stock.specifics or not stock.metal_type


def stock_metadata_parse_eligible(stock: Stock, *, force: bool = False) -> bool:
    """Return True when the row should get its one automatic parser attempt."""
    if force:
        return True
    if stock.parsed_at:
        return False
    if stock.parser_attempted_at:
        return False
    return stock_metadata_incomplete(stock)


def enqueue_stock_metadata_parse(stock_id: UUID | str, *, force: bool = False) -> None:
    """Queue metadata parsing once the surrounding DB transaction commits."""
    transaction.on_commit(lambda: parse_stock_item_task.delay(str(stock_id), force=force))


def queue_metadata_parse_if_eligible(stock: Stock) -> bool:
    """Queue a parse for a freshly written stock row, if it needs and deserves one.

    This is the one place the eligibility test and enqueue are paired (ADR
    0039). It returns whether a task was queued so callers and tests can assert
    on the decision.
    """
    if not stock_metadata_parse_eligible(stock):
        logger.debug("Stock %s has complete metadata; no parser task queued.", stock.id)
        return False
    enqueue_stock_metadata_parse(stock.id)
    return True


def _connection_hygiene() -> None:
    """Recycle stale connections, except when a caller's transaction owns ours.

    Tasks executed eagerly inside a request or a test run inside the caller's
    atomic block; closing connections there would drop the caller's own.
    """
    if not connection.in_atomic_block:
        close_old_connections()


@shared_task(name="apps.purchasing.tasks.parse_stock_item_task")
def parse_stock_item_task(stock_id: str, force: bool = False) -> None:
    """Parse one active stock row's missing metadata."""
    try:
        _connection_hygiene()
        stock = Stock.objects.filter(id=stock_id, is_active=True).first()
        if stock is None:
            logger.info("Skipping stock metadata parse for inactive/missing stock %s", stock_id)
            return
        if not stock_metadata_parse_eligible(stock, force=force):
            logger.info("Skipping stock %s: not eligible for a parser attempt", stock_id)
            return
        auto_parse_stock_item(stock, force=force)
    except Exception as exc:
        logger.exception("Error parsing stock metadata for %s", stock_id)
        persist_app_error(
            exc,
            AppErrorContext(additional_context={"stock_id": str(stock_id), "force": force}),
        )
        raise


@shared_task(name="apps.purchasing.tasks.parse_unparsed_stock_items_task")
def parse_unparsed_stock_items_task(limit: int = 50) -> None:
    """Queue a bounded catch-up batch for active stock with missing metadata."""
    try:
        _connection_hygiene()
        capped = max(1, min(int(limit), MAX_CATCH_UP_BATCH))
        stock_ids = list(
            Stock.objects.filter(
                is_active=True, parsed_at__isnull=True, parser_attempted_at__isnull=True
            )
            .filter(_incomplete_metadata_query())
            .order_by("date", "id")
            .values_list("id", flat=True)[:capped]
        )
        for stock_id in stock_ids:
            parse_stock_item_task.delay(str(stock_id))
        logger.info("Queued %s stock metadata parse tasks.", len(stock_ids))
    except Exception as exc:
        logger.exception("Error queueing stock metadata parse batch.")
        persist_app_error(
            exc,
            AppErrorContext(
                additional_context={"task": "parse_unparsed_stock_items_task", "limit": limit}
            ),
        )
        raise


def queue_purchase_order_push(po: PurchaseOrder) -> None:
    """Queue the Xero push for ``po`` if Docketworks owns it and Xero needs it.

    Dispatched by NAME rather than by importing the task: the push lives in
    ``apps.xero`` because it is a Xero concern, and a domain app may not import
    an integration (import-linter's layer contract). The task name is already
    an operational contract in this module's own words, so naming it here costs
    nothing that renaming it would not already cost.

    Queued on ``transaction.on_commit`` so a worker can never read a purchase
    order the caller's transaction rolls back — the same rule the stock parser
    above follows.

    Xero needs the order once it has gone to the supplier, and needs it kept
    current after that. A draft that has never been sent is still ours alone.
    """
    if po.created_by_id is None:
        return
    if po.xero_id is None and po.status == "draft":
        return
    po_id = str(po.id)
    transaction.on_commit(lambda: current_app.send_task(PUSH_PURCHASE_ORDER_TASK, args=[po_id]))
