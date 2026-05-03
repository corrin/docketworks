import logging
import time
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.db import models
from django.utils import timezone
from xero_python.accounting import AccountingApi

from apps.accounting.models import Bill, CreditNote, Invoice, Quote
from apps.client.models import Client
from apps.purchasing.models import PurchaseOrder, Stock
from apps.workflow.api.xero.auth import api_client, get_tenant_id, get_token
from apps.workflow.api.xero.client import quota_floor_breached
from apps.workflow.api.xero.payroll import (
    get_all_pay_slips_for_sync,
    get_pay_runs_for_sync,
)
from apps.workflow.api.xero.push import (  # noqa: F401
    bulk_create_contacts_in_xero,
    create_client_contact_in_xero,
    get_all_xero_contacts,
    map_costline_to_expense_entry,
    map_costline_to_time_entry,
    sync_client_to_xero,
    sync_costlines_to_xero,
    sync_expense_entries_bulk,
    sync_job_to_xero,
    sync_time_entries_bulk,
)
from apps.workflow.api.xero.seed import (  # noqa: F401
    seed_clients_to_xero,
    seed_jobs_to_xero,
    sync_single_contact,
    sync_single_invoice,
    sync_single_pay_run,
)
from apps.workflow.api.xero.transforms import process_xero_data  # noqa: F401
from apps.workflow.api.xero.transforms import sync_clients  # noqa: F401
from apps.workflow.api.xero.transforms import (
    sync_accounts,
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
from apps.workflow.api.xero.xero import get_xero_items
from apps.workflow.exceptions import XeroQuotaFloorReached, XeroValidationError
from apps.workflow.models import (
    CompanyDefaults,
    XeroAccount,
    XeroPayRun,
    XeroPaySlip,
    XeroSyncCursor,
)
from apps.workflow.services.error_persistence import persist_xero_error
from apps.workflow.utils import get_machine_id

logger = logging.getLogger("xero")

SLEEP_TIME = 1  # Sleep after every API call to avoid hitting rate limits


def get_last_modified_time(model):
    """Get the latest modification time for a model"""
    last_modified = model.objects.aggregate(models.Max("xero_last_modified"))[
        "xero_last_modified__max"
    ]

    if last_modified:
        last_modified = last_modified - timedelta(seconds=1)
        return last_modified.isoformat()

    return "2000-01-01T00:00:00Z"


def get_sync_cursor(entity_key, model):
    """Get the sync cursor for an entity, falling back to DB high-water mark.

    Only the hourly sync should call this. Webhooks never touch cursors.
    On first run after deployment, no cursor exists yet — fall back to the
    model's max xero_last_modified (same as previous behavior).
    """
    cursor = XeroSyncCursor.objects.filter(entity_key=entity_key).first()
    if not cursor:
        return get_last_modified_time(model)
    # Apply same 1-second backoff as get_last_modified_time for overlap safety
    return (cursor.last_modified - timedelta(seconds=1)).isoformat()


def update_sync_cursor(entity_key, timestamp):
    """Upsert the sync cursor after a successful sync run."""
    XeroSyncCursor.objects.update_or_create(
        entity_key=entity_key,
        defaults={"last_modified": timestamp},
    )


def process_xero_item(item, sync_function, entity_type):
    """Process one Xero item and return an event.

    Args:
        item: Xero object to sync.
        sync_function: Callable that saves the item.
        entity_type: Name of the entity for event messages.

    Returns:
        Tuple of success flag and event dictionary.
    """
    try:
        sync_function([item])
    except XeroValidationError as exc:
        persist_xero_error(exc)
        return False, {
            "datetime": timezone.now().isoformat(),
            "severity": "error",
            "message": str(exc),
            "progress": None,
        }
    except Exception as exc:
        return False, {
            "datetime": timezone.now().isoformat(),
            "severity": "error",
            "message": "Unexpected: " + str(exc),
            "progress": None,
        }
    return True, {
        "datetime": timezone.now().isoformat(),
        "entity": entity_type,
        "severity": "info",
        "message": f"Synced {entity_type}",
        "progress": None,
    }


def sync_xero_data(
    xero_entity_type,
    our_entity_type,
    xero_api_fetch_function,
    sync_function,
    last_modified_time,
    additional_params=None,
    pagination_mode="single",
    xero_tenant_id=None,
    entity_key=None,
):
    """Sync data from Xero with pagination support.

    Args:
        xero_entity_type: Name of the Xero collection.
        our_entity_type: Local entity name for messages.
        xero_api_fetch_function: API call used to fetch data.
        sync_function: Function that persists items.
        last_modified_time: Timestamp for incremental fetches.
        additional_params: Extra parameters for the API call.
        pagination_mode: Offset or page pagination style.
        xero_tenant_id: Optional tenant identifier.
        entity_key: Key for updating the sync cursor after success.

    Yields:
        Progress or error events as dictionaries.
    """

    if xero_tenant_id is None:
        xero_tenant_id = get_tenant_id()

    # Production safety check
    current_machine_id = get_machine_id()
    is_production = current_machine_id == settings.PRODUCTION_MACHINE_ID

    if is_production and xero_tenant_id != settings.PRODUCTION_XERO_TENANT_ID:
        logger.warning(
            f"Attempted to sync in production with non-production tenant ID: {xero_tenant_id}"
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
    params = {
        "if_modified_since": last_modified_time,
        "xero_tenant_id": xero_tenant_id,
    }

    # API quirk: get_xero_items doesn't support tenant_id
    if xero_api_fetch_function == get_xero_items:
        params.pop("xero_tenant_id", None)

    # Pagination setup
    page_size = 100
    if pagination_mode == "page" and xero_entity_type not in ["quotes", "accounts"]:
        params.update({"page_size": page_size, "order": "UpdatedDateUTC ASC"})

    if additional_params:
        params.update(additional_params)

    # Fetch and process data
    page = 1
    offset = 0
    total_processed = 0
    max_updated_date_utc = None

    while True:
        if quota_floor_breached(settings.XERO_AUTOMATED_DAY_FLOOR):
            # Raise (don't yield-warning-and-return). The yield+return pattern
            # is right for human-fix-required config errors (see the tenant
            # mismatch above) but wrong for an operational abort: the caller
            # would consume the warning and continue to its "Sync stream
            # ended"/"success" marker, masking the abort. Raising propagates
            # through `yield from` to XeroSyncService.run_sync, which has a
            # XeroQuotaFloorReached branch that emits sync_status:"aborted".
            raise XeroQuotaFloorReached(
                f"Skipping {our_entity_type}: Xero day quota at floor "
                f"({settings.XERO_AUTOMATED_DAY_FLOOR})"
            )

        # Update pagination params
        if pagination_mode == "offset":
            params["offset"] = offset
        elif pagination_mode == "page":
            params["page"] = page

        # Fetch data
        entities = xero_api_fetch_function(**params)
        time.sleep(SLEEP_TIME)

        if entities is None:
            raise ValueError(f"API returned None for {xero_entity_type}")

        # Extract items
        items = (
            entities
            if isinstance(entities, list)
            else getattr(entities, xero_entity_type)
        )

        if not items:
            break

        try:
            sync_function(items)
            total_processed += len(items)
        except XeroValidationError as exc:
            persist_xero_error(exc)
            raise
        except Exception:
            raise

        # Track the max updated_date_utc across all pages for cursor update
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
            "message": f"Processed {len(items)} {our_entity_type}",
            "progress": None,
            "recordsUpdated": len(items),
        }

        # Check if done
        if len(items) < page_size or pagination_mode == "single":
            break

        # Update pagination
        if pagination_mode == "page":
            page += 1
        elif pagination_mode == "offset":
            offset = max(item.journal_number for item in items) + 1

    # Update the sync cursor if we processed items and have a valid timestamp
    if entity_key and total_processed > 0 and not max_updated_date_utc:
        logger.warning(
            f"Synced {total_processed} {our_entity_type} but none had "
            f"updated_date_utc — cursor not advanced for '{entity_key}'"
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


# Entity configurations - ordered by business importance (accounts first, journals last)
ENTITY_CONFIGS = {
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
        Client,
        "get_contacts",
        sync_clients,
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
        lambda items: sync_entities(
            items, CreditNote, "credit_note_id", transform_credit_note
        ),
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
        lambda items: sync_entities(
            items, XeroPaySlip, "pay_slip_id", transform_pay_slip
        ),
        None,
        "single",  # All slips fetched at once
    ),
    # Journal Sync is disabled.
    # It takes ages, and we're barely using them
}


def _resolve_api_method(api_method):
    """Resolve an ENTITY_CONFIGS api_method string to a callable."""
    if api_method == "get_xero_items":
        return get_xero_items
    if api_method == "get_pay_runs_for_sync":
        return get_pay_runs_for_sync
    if api_method == "get_all_pay_slips_for_sync":
        return get_all_pay_slips_for_sync
    return getattr(AccountingApi(api_client), api_method)


def sync_all_xero_data(
    use_latest_timestamps=True, days_back=30, entities=None, force=False
):
    """Sync Xero data - either using latest timestamps or looking back N days."""
    token = get_token()
    if not token:
        logger.warning("No valid Xero token found")
        return

    # Safety net: don't sync until seeding is complete (prod IDs cleared, dev IDs set).
    # Targeted syncs (e.g. --entity accounts) during setup can pass force=True.
    if not force:
        company = CompanyDefaults.get_solo()
        if not company.enable_xero_sync:
            logger.warning(
                "Xero sync not ready: enable_xero_sync is False. "
                "In DEV: Run 'python manage.py seed_xero_from_database' first. "
                "In Prod: Set using the gui"
            )
            return

    if entities is None:
        entities = list(ENTITY_CONFIGS.keys())

    # Get timestamps
    if use_latest_timestamps:
        timestamps = {
            entity: get_sync_cursor(entity, ENTITY_CONFIGS[entity][2])
            for entity in ENTITY_CONFIGS
        }
    else:
        older_time = (timezone.now() - timedelta(days=days_back)).isoformat()
        timestamps = {entity: older_time for entity in ENTITY_CONFIGS}

    # Sync each entity
    for entity in entities:
        if entity not in ENTITY_CONFIGS:
            logger.error(f"Unknown entity type: {entity}")
            continue

        (
            xero_type,
            our_type,
            model,
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


def sync_local_stock_to_xero():
    """Sync local stock items to Xero as part of the main sync process."""
    try:
        yield {
            "datetime": timezone.now().isoformat(),
            "entity": "stock_local_to_xero",
            "severity": "info",
            "message": "Starting sync of local stock items to Xero",
            "progress": None,
        }

        from apps.workflow.api.xero.stock_sync import sync_all_local_stock_to_xero

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
            "message": f"Completed local stock sync: {result['success_rate']:.1f}% success rate",
            "status": "Completed",
            "progress": 1.0,
        }

    except XeroQuotaFloorReached:
        # Bubble up — XeroSyncService.run_sync's quota-floor branch handles
        # this with sync_status:"aborted". Catching here would degrade an
        # abort to a generic error event and let run_sync's success marker
        # still fire.
        raise
    except Exception as e:
        logger.error(f"Error syncing local stock to Xero: {str(e)}")
        yield {
            "datetime": timezone.now().isoformat(),
            "entity": "stock_local_to_xero",
            "severity": "error",
            "message": f"Error syncing local stock to Xero: {str(e)}",
            "progress": None,
        }


def one_way_sync_all_xero_data(entities=None, force=False):
    """Normal sync using latest timestamps"""
    yield from sync_all_xero_data(
        use_latest_timestamps=True, entities=entities, force=force
    )


def deep_sync_xero_data(days_back=30, entities=None):
    """Perform a deep synchronisation over a time window.

    Args:
        days_back: Number of days of history to retrieve.
        entities: Optional list of entity keys to sync.

    Yields:
        Progress or error events as dictionaries.
    """
    yield from sync_all_xero_data(
        use_latest_timestamps=False, days_back=days_back, entities=entities
    )


def synchronise_xero_data(delay_between_requests=1):
    """Yield progress events while performing a full Xero synchronisation."""
    from apps.workflow.api.xero.payroll import sync_xero_pay_items

    # `sync_xero_pay_items` runs before any per-page gate and isn't itself
    # gated; without this orchestrator-level check it would 429 below the
    # floor on every breached sync. The per-page gate in `sync_xero_data`
    # never gets a chance because the orchestrator crashes first.
    if quota_floor_breached(settings.XERO_AUTOMATED_DAY_FLOOR):
        # Raise rather than yield-and-return: the latter would let
        # `XeroSyncService.run_sync` finish normally and emit
        # sync_status:"success", silently hiding the abort. Raising lets
        # the run_sync XeroQuotaFloorReached branch emit "aborted" instead.
        raise XeroQuotaFloorReached(
            f"Skipping sync: Xero day quota at floor "
            f"({settings.XERO_AUTOMATED_DAY_FLOOR})"
        )

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
        company_defaults = CompanyDefaults.get_solo()
        now = timezone.now()

        # Sync pay items (leave types + earnings rates) - lightweight, 2 API calls
        result = sync_xero_pay_items()
        lt = result["leave_types"]
        er = result["earnings_rates"]
        yield {
            "datetime": timezone.now().isoformat(),
            "entity": "pay_items",
            "severity": "info",
            "message": f"Synced pay items: {lt['created'] + lt['updated']} leave types, {er['created'] + er['updated']} earnings rates",
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
