"""The Xero sync engine: entity configs, page loop, cursors, orchestration.

Progress crosses process boundaries as ``XeroSyncEvent`` dicts — appended to
the shared-cache message list by the worker task and replayed by the SSE
stream. The quota floor aborts by RAISING ``XeroQuotaFloorReached`` (never
yield-and-return): a yielded warning would let the consumer run on to its
"success" terminal marker and mask the abort.
"""

import logging
import time
from collections.abc import Callable, Iterator, Sequence
from datetime import timedelta
from typing import Any, TypedDict

from django.conf import settings
from django.db import models
from django.utils import timezone
from xero_python.accounting import AccountingApi

from apps.accounting.models import Bill, CreditNote, Invoice, Quote
from apps.accounting.registry import is_accounting_enabled
from apps.company.models import Company
from apps.core.errors import persist_app_error
from apps.core.models import CompanyDefaults
from apps.purchasing.models import PurchaseOrder, Stock
from apps.xero.auth import (
    NoValidXeroTokenError,
    get_api_client,
    get_tenant_id,
    get_valid_token,
)
from apps.xero.client import XeroQuotaFloorReached, quota_floor_breached
from apps.xero.e2e_artifacts import drop_e2e_artifacts
from apps.xero.models import XeroAccount, XeroPayRun, XeroPaySlip, XeroSyncCursor
from apps.xero.payroll_sync import (
    get_all_pay_slips_for_sync,
    get_pay_runs_for_sync,
    sync_xero_pay_items,
)
from apps.xero.stock_sync import get_xero_items
from apps.xero.transforms import (
    sync_accounts,
    sync_companies,
    sync_entities,
    transform_bill,
    transform_credit_note,
    transform_invoice,
    transform_pay_run,
    transform_pay_slip,
    transform_purchase_order,
    transform_quote,
    transform_stock,
)
from apps.xero.validation import XeroValidationError, persist_xero_error

logger = logging.getLogger(__name__)

SLEEP_TIME = 1  # Sleep after every API call to avoid hitting rate limits


class XeroSyncEvent(TypedDict, total=False):
    """One progress/error event; JSON-shaped for the cache list and SSE."""

    datetime: str
    entity: str
    severity: str
    message: str
    status: str
    progress: float | None
    recordsUpdated: int


def get_last_modified_time(model: type[models.Model]) -> str:
    """Get the latest modification time for a model (fallback high-water mark)."""
    # _default_manager, not .objects: mypy's type[Model] carries only the
    # documented generic accessor.
    last_modified = model._default_manager.aggregate(models.Max("xero_last_modified"))[
        "xero_last_modified__max"
    ]

    if last_modified:
        backed_off: str = (last_modified - timedelta(seconds=1)).isoformat()
        return backed_off

    return "2000-01-01T00:00:00Z"


def get_sync_cursor(entity_key: str, model: type[models.Model]) -> str:
    """Get the sync cursor for an entity, falling back to the DB high-water mark.

    Only the hourly sync should call this. Webhooks never touch cursors.
    On first run after deployment, no cursor exists yet — fall back to the
    model's max xero_last_modified (same as previous behavior).
    """
    cursor = XeroSyncCursor.objects.filter(entity_key=entity_key).first()
    if not cursor:
        return get_last_modified_time(model)
    # Apply same 1-second backoff as get_last_modified_time for overlap safety
    return (cursor.last_modified - timedelta(seconds=1)).isoformat()


def update_sync_cursor(entity_key: str, timestamp: Any) -> None:
    """Upsert the sync cursor after a successful sync run."""
    XeroSyncCursor.objects.update_or_create(
        entity_key=entity_key,
        defaults={"last_modified": timestamp},
    )


def sync_xero_data(  # noqa: C901, PLR0912, PLR0913, PLR0915, PLR0917 -- ported v1 engine loop; one pass owns fetch, gate, filter, persist, cursor
    xero_entity_type: str,
    our_entity_type: str,
    xero_api_fetch_function: Callable[..., Any],
    sync_function: Callable[[list[Any]], Any],
    last_modified_time: str,
    additional_params: dict[str, Any] | None = None,
    pagination_mode: str = "single",
    xero_tenant_id: str | None = None,
    entity_key: str | None = None,
) -> Iterator[XeroSyncEvent]:
    """Sync one entity from Xero with pagination support.

    Yields progress or error events; raises ``XeroQuotaFloorReached`` when the
    day quota gate closes mid-run.
    """
    if xero_tenant_id is None:
        xero_tenant_id = get_tenant_id()

    # Production safety check. v1 keyed "is this production" off a machine-id
    # setting v2 does not carry; DEBUG-off is v2's production-like signal.
    is_production = not settings.DEBUG

    if is_production and xero_tenant_id != settings.PRODUCTION_XERO_TENANT_ID:
        logger.warning(
            "Attempted to sync in production with non-production tenant ID: %s",
            xero_tenant_id,
        )
        yield {
            "datetime": timezone.now().isoformat(),
            "entity": our_entity_type,
            "severity": "warning",
            "message": "Sync aborted: Production/tenant mismatch",
            "progress": 0.0,
        }
        return

    # Setup parameters
    params: dict[str, Any] = {
        "if_modified_since": last_modified_time,
        "xero_tenant_id": xero_tenant_id,
    }

    # API quirk: get_xero_items doesn't support tenant_id
    if xero_api_fetch_function is get_xero_items:
        params.pop("xero_tenant_id", None)

    # Pagination setup
    page_size = 100
    if pagination_mode == "page" and xero_entity_type not in ["quotes", "accounts"]:
        params.update({"page_size": page_size, "order": "UpdatedDateUTC ASC"})

    if additional_params:
        params.update(additional_params)

    # Fetch and process data
    page = 1
    total_processed = 0
    max_updated_date_utc = None

    while True:
        floor = CompanyDefaults.get_solo().xero_automated_day_floor
        if quota_floor_breached(floor):
            # Raise (don't yield-warning-and-return). The yield+return pattern
            # is right for human-fix-required config errors (see the tenant
            # mismatch above) but wrong for an operational abort: the caller
            # would consume the warning and continue to its "Sync stream
            # ended"/"success" marker, masking the abort. Raising propagates
            # through `yield from` to the worker task, which has a
            # XeroQuotaFloorReached branch that emits sync_status:"aborted".
            raise XeroQuotaFloorReached(
                f"Skipping {our_entity_type}: Xero day quota at floor ({floor})"
            )

        # Update pagination params
        if pagination_mode == "page":
            params["page"] = page

        # Fetch data
        entities = xero_api_fetch_function(**params)
        time.sleep(SLEEP_TIME)

        if entities is None:
            raise ValueError(f"API returned None for {xero_entity_type}")

        # Extract items
        items = entities if isinstance(entities, list) else getattr(entities, xero_entity_type)

        if not items:
            break

        # Drop objects a finished E2E run created in Xero. Filtered here rather
        # than inside the sync functions so a suppressed contact and the
        # documents referencing it are dropped together, and pagination still
        # terminates on the fetched page rather than the filtered one.
        items_to_sync = drop_e2e_artifacts(items, our_entity_type, xero_tenant_id)

        if items_to_sync:
            try:
                sync_function(items_to_sync)
                total_processed += len(items_to_sync)
            except XeroValidationError as exc:
                persist_xero_error(exc)
                raise
            except Exception as exc:
                persist_app_error(exc)
                raise
        else:
            pass  # Whole page suppressed; the cursor below still advances past it.

        # Track the max updated_date_utc across all pages for cursor update.
        # Deliberately over the fetched items, not the filtered ones, so the
        # cursor advances past suppressed objects instead of refetching them
        # from Xero every hour.
        for item in items:
            item_updated = getattr(item, "updated_date_utc", None)
            if item_updated and (
                max_updated_date_utc is None or item_updated > max_updated_date_utc
            ):
                max_updated_date_utc = item_updated

        yield {
            "datetime": timezone.now().isoformat(),
            "entity": our_entity_type,
            "severity": "info",
            "message": f"Processed {len(items_to_sync)} {our_entity_type}",
            "progress": None,
            "recordsUpdated": len(items_to_sync),
        }

        # Check if done
        if len(items) < page_size or pagination_mode == "single":
            break

        # Update pagination
        if pagination_mode == "page":
            page += 1

    # Update the sync cursor if we processed items and have a valid timestamp
    if entity_key and total_processed > 0 and not max_updated_date_utc:
        logger.warning(
            "Synced %d %s but none had updated_date_utc — cursor not advanced for '%s'",
            total_processed,
            our_entity_type,
            entity_key,
        )
    if entity_key and max_updated_date_utc:
        update_sync_cursor(entity_key, max_updated_date_utc)

    yield {
        "datetime": timezone.now().isoformat(),
        "entity": our_entity_type,
        "severity": "info",
        "message": f"Completed sync of {our_entity_type}",
        "status": "Completed",
        "progress": 1.0,
    }


# (xero_collection, our_name, model, api_method_name, sync_func, extra_params,
# pagination_mode) — ordered by business importance.
EntityConfig = tuple[
    str,
    str,
    type[models.Model],
    str,
    Callable[[list[Any]], Any],
    dict[str, Any] | None,
    str,
]

ENTITY_CONFIGS: dict[str, EntityConfig] = {
    "accounts": (
        "accounts",
        "accounts",
        XeroAccount,
        "get_accounts",
        sync_accounts,
        None,
        "single",
    ),
    "contacts": (
        "contacts",
        "contacts",
        Company,
        "get_contacts",
        sync_companies,
        {"include_archived": True},
        "page",
    ),
    "invoices": (
        "invoices",
        "invoices",
        Invoice,
        "get_invoices",
        lambda items: sync_entities(items, Invoice, "invoice_id", transform_invoice),
        {"where": 'Type=="ACCREC"'},
        "page",
    ),
    "quotes": (
        "quotes",
        "quotes",
        Quote,
        "get_quotes",
        lambda items: sync_entities(items, Quote, "quote_id", transform_quote),
        None,
        "single",
    ),
    "purchase_orders": (
        "purchase_orders",
        "purchase_orders",
        PurchaseOrder,
        "get_purchase_orders",
        lambda items: sync_entities(
            items, PurchaseOrder, "purchase_order_id", transform_purchase_order
        ),
        None,
        "page",
    ),
    "bills": (
        "invoices",
        "bills",
        Bill,
        "get_invoices",
        lambda items: sync_entities(items, Bill, "invoice_id", transform_bill),
        {"where": 'Type=="ACCPAY"'},
        "page",
    ),
    "stock": (
        "items",
        "stock",
        Stock,
        "get_xero_items",
        lambda items: sync_entities(items, Stock, "item_id", transform_stock),
        None,
        "single",
    ),
    "credit_notes": (
        "credit_notes",
        "credit_notes",
        CreditNote,
        "get_credit_notes",
        lambda items: sync_entities(items, CreditNote, "credit_note_id", transform_credit_note),
        None,
        "page",
    ),
    # Payroll entities - use PayrollNzApi, not AccountingApi
    # Pay runs: Xero is master, local DB is cache. Delete orphans on sync.
    "pay_runs": (
        "pay_runs",
        "pay_runs",
        XeroPayRun,
        "get_pay_runs_for_sync",  # Custom API function
        lambda items: sync_entities(
            items, XeroPayRun, "pay_run_id", transform_pay_run, delete_orphans=True
        ),
        None,
        "single",  # No pagination for pay runs
    ),
    "pay_slips": (
        "pay_slips",
        "pay_slips",
        XeroPaySlip,
        "get_all_pay_slips_for_sync",  # Custom API function
        lambda items: sync_entities(items, XeroPaySlip, "pay_slip_id", transform_pay_slip),
        None,
        "single",  # All slips fetched at once
    ),
    # Journal sync is disabled: it takes ages, and we barely use them.
}


def _resolve_api_method(api_method: str) -> Callable[..., Any]:
    """Resolve an ENTITY_CONFIGS api_method string to a callable."""
    if api_method == "get_xero_items":
        return get_xero_items
    if api_method == "get_pay_runs_for_sync":
        return get_pay_runs_for_sync
    if api_method == "get_all_pay_slips_for_sync":
        return get_all_pay_slips_for_sync
    method: Callable[..., Any] = getattr(AccountingApi(get_api_client()), api_method)
    return method


def sync_all_xero_data(
    use_latest_timestamps: bool = True,
    days_back: int = 30,
    entities: Sequence[str] | None = None,
    force: bool = False,
) -> Iterator[XeroSyncEvent]:
    """Sync Xero data - either using latest timestamps or looking back N days."""
    # Safety net: don't sync until setup is complete. Targeted syncs during
    # setup can pass force=True.
    if not force and not is_accounting_enabled():
        logger.warning(
            "Xero sync not ready: enable_xero_sync is False. Enable it via CompanyDefaults."
        )
        return

    token = get_valid_token()
    if not token:
        message = "No valid Xero token found"
        logger.warning(message)
        raise NoValidXeroTokenError(message)

    if entities is None:
        entities = list(ENTITY_CONFIGS.keys())

    # Get timestamps
    if use_latest_timestamps:
        timestamps = {
            entity: get_sync_cursor(entity, ENTITY_CONFIGS[entity][2]) for entity in ENTITY_CONFIGS
        }
    else:
        older_time = (timezone.now() - timedelta(days=days_back)).isoformat()
        timestamps = dict.fromkeys(ENTITY_CONFIGS, older_time)

    # Sync each entity
    for entity in entities:
        if entity not in ENTITY_CONFIGS:
            logger.error("Unknown entity type: %s", entity)
            continue

        (
            xero_type,
            our_type,
            _model,
            api_method,
            sync_func,
            params,
            pagination,
        ) = ENTITY_CONFIGS[entity]

        api_func = _resolve_api_method(api_method)

        yield from sync_xero_data(
            xero_entity_type=xero_type,
            our_entity_type=our_type,
            xero_api_fetch_function=api_func,
            sync_function=sync_func,
            last_modified_time=timestamps[entity],
            additional_params=params,
            pagination_mode=pagination,
            entity_key=entity if use_latest_timestamps else None,
        )

    # After syncing from Xero, sync local stock items back to Xero (bidirectional)
    if "stock" in entities or entities == list(ENTITY_CONFIGS.keys()):
        yield from sync_local_stock_to_xero()


def sync_local_stock_to_xero() -> Iterator[XeroSyncEvent]:
    """Sync local stock items to Xero as part of the main sync process."""
    try:
        yield {
            "datetime": timezone.now().isoformat(),
            "entity": "stock_local_to_xero",
            "severity": "info",
            "message": "Starting sync of local stock items to Xero",
            "progress": None,
        }

        # Call-time import: the push half lands with stage 2a.7; the engine
        # must not fail to import while only the pull half exists.
        from apps.xero.stock_sync import sync_all_local_stock_to_xero  # noqa: PLC0415

        # Sync local stock items to Xero (limit to avoid overwhelming)
        result = sync_all_local_stock_to_xero(limit=50)

        if result["synced_count"] > 0:
            yield {
                "datetime": timezone.now().isoformat(),
                "entity": "stock_local_to_xero",
                "severity": "info",
                "message": f"Synced {result['synced_count']} local stock items to Xero",
                "progress": None,
                "recordsUpdated": result["synced_count"],
            }

        if result["failed_count"] > 0:
            yield {
                "datetime": timezone.now().isoformat(),
                "entity": "stock_local_to_xero",
                "severity": "warning",
                "message": f"Failed to sync {result['failed_count']} stock items to Xero",
                "progress": None,
            }

        yield {
            "datetime": timezone.now().isoformat(),
            "entity": "stock_local_to_xero",
            "severity": "info",
            "message": (f"Completed local stock sync: {result['success_rate']:.1f}% success rate"),
            "status": "Completed",
            "progress": 1.0,
        }

    except XeroQuotaFloorReached:
        # Bubble up — the worker task's quota-floor branch handles this with
        # sync_status:"aborted". Catching here would degrade an abort to a
        # generic error event and let the success marker still fire.
        raise
    # deliberate-swallow: outbound stock push is best-effort inside the sync
    # run — its failure becomes an error event, never a lost inbound sync
    except Exception as exc:  # noqa: BLE001
        persist_app_error(exc)
        logger.error("Error syncing local stock to Xero: %s", exc)
        yield {
            "datetime": timezone.now().isoformat(),
            "entity": "stock_local_to_xero",
            "severity": "error",
            "message": f"Error syncing local stock to Xero: {exc}",
            "progress": None,
        }


def one_way_sync_all_xero_data(
    entities: Sequence[str] | None = None, force: bool = False
) -> Iterator[XeroSyncEvent]:
    """Run a normal sync using the latest cursor timestamps."""
    yield from sync_all_xero_data(use_latest_timestamps=True, entities=entities, force=force)


def deep_sync_xero_data(
    days_back: int = 30, entities: Sequence[str] | None = None
) -> Iterator[XeroSyncEvent]:
    """Perform a deep synchronisation over a time window."""
    yield from sync_all_xero_data(
        use_latest_timestamps=False, days_back=days_back, entities=entities
    )


def synchronise_xero_data() -> Iterator[XeroSyncEvent]:
    """Yield progress events while performing a full Xero synchronisation."""
    from django.core.cache import cache  # noqa: PLC0415 -- call-time: keep module import cheap

    company_defaults = CompanyDefaults.get_solo()
    if not company_defaults.enable_xero_sync:
        logger.info("Xero sync skipped: enable_xero_sync is False")
        yield {
            "datetime": timezone.now().isoformat(),
            "entity": "sync",
            "severity": "warning",
            "message": "Xero sync skipped: enable_xero_sync is False",
        }
        return

    # `sync_xero_pay_items` runs before any per-page gate and isn't itself
    # gated; without this orchestrator-level check it would 429 below the
    # floor on every breached sync. The per-page gate in `sync_xero_data`
    # never gets a chance because the orchestrator crashes first.
    floor = company_defaults.xero_automated_day_floor
    if quota_floor_breached(floor):
        # Raise rather than yield-and-return: the latter would let the worker
        # finish normally and emit sync_status:"success", silently hiding the
        # abort. Raising lets its XeroQuotaFloorReached branch emit "aborted".
        raise XeroQuotaFloorReached(f"Skipping sync: Xero day quota at floor ({floor})")

    if not cache.add("xero_sync_lock", True, timeout=60 * 60 * 4):
        logger.info("Skipping sync - another sync is running")
        yield {
            "datetime": timezone.now().isoformat(),
            "entity": "sync",
            "severity": "warning",
            "message": "Skipping sync - another sync is already running",
        }
        return

    try:
        now = timezone.now()

        # Sync pay items (leave types + earnings rates) - lightweight, 2 API
        # calls. Emit the same Processed/Completed pair as `sync_xero_data` so
        # consumers treat pay_items consistently with every other entity.
        result = sync_xero_pay_items()
        lt = result["leave_types"]
        er = result["earnings_rates"]
        yield {
            "datetime": timezone.now().isoformat(),
            "entity": "pay_items",
            "severity": "info",
            "message": (
                f"Synced pay items: {lt['created'] + lt['updated']} leave types, "
                f"{er['created'] + er['updated']} earnings rates"
            ),
            "progress": None,
            "recordsUpdated": result["records_updated"],
        }
        yield {
            "datetime": timezone.now().isoformat(),
            "entity": "pay_items",
            "severity": "info",
            "message": "Completed sync of pay_items",
            "status": "Completed",
            "progress": 1.0,
        }

        # Check if deep sync needed
        if (
            not company_defaults.last_xero_deep_sync
            or (now - company_defaults.last_xero_deep_sync).days >= 30
        ):
            is_first_sync = company_defaults.last_xero_deep_sync is None
            days_to_sync = 5000 if is_first_sync else 90

            yield from deep_sync_xero_data(days_back=days_to_sync)
            company_defaults.last_xero_deep_sync = now
            company_defaults.save()

        # Normal sync
        yield from one_way_sync_all_xero_data()

        company_defaults.last_xero_sync = now
        company_defaults.save()

    finally:
        cache.delete("xero_sync_lock")
