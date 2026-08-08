"""Stock ↔ Xero items: inbound fetch and the outbound push.

v1 split these across ``xero.py`` (fetch) and ``stock_sync.py`` (push); both
directions of the same concept live here. The per-item ``sync_stock_to_xero``
of v1 had no callers outside its barrel re-export and is not ported; the
batched ``sync_all_local_stock_to_xero`` is the live path. The
``update_stock_item_codes``/``fix_long_item_codes`` repair utilities stay
deferred with the other dev tooling.
"""

import logging
import time
from datetime import datetime
from typing import Any

from django.utils import timezone
from xero_python.accounting import AccountingApi

from apps.core.errors import persist_app_error
from apps.core.models import CompanyDefaults
from apps.purchasing.models import Stock
from apps.xero.auth import get_api_client, get_tenant_id
from apps.xero.client import XeroQuotaFloorReached, quota_floor_breached
from apps.xero.constants import SLEEP_TIME
from apps.xero.models import XeroAccount

logger = logging.getLogger(__name__)


def get_xero_items(if_modified_since: datetime | str | None = None, **kwargs: Any) -> Any:
    """Fetch Xero inventory items (the sync loop's custom fetcher for "stock").

    Accepts an ISO string as well as a datetime: the sync loop threads
    cursor timestamps through as strings. ``kwargs`` absorbs the loop's
    generic per-entity parameters this fetcher does not use (page etc.).
    """
    del kwargs  # the generic loop signature; unused by this fetcher
    logger.info("Fetching Xero Items. If modified since: %s", if_modified_since)

    tenant_id = get_tenant_id()
    accounting_api = AccountingApi(get_api_client())

    if isinstance(if_modified_since, str):
        if_modified_since = datetime.fromisoformat(if_modified_since.replace("Z", "+00:00"))

    try:
        if if_modified_since is None:
            logger.info("No 'if_modified_since' provided, fetching all items.")
            items = accounting_api.get_items(xero_tenant_id=tenant_id)
        else:
            items = accounting_api.get_items(
                xero_tenant_id=tenant_id, if_modified_since=if_modified_since
            )
    except Exception as exc:
        persist_app_error(exc)
        raise
    logger.info("Successfully fetched %d Xero Items.", len(items.items or []))
    return items


def fetch_all_xero_items(api: AccountingApi, tenant_id: str) -> dict[str, Any]:
    """Fetch all Xero items and return a code -> item lookup dictionary.

    More efficient than per-item queries, and handles special characters in
    codes that can't be escaped in WHERE clauses (e.g., double quotes).
    """
    try:
        resp = api.get_items(tenant_id)
        time.sleep(SLEEP_TIME)
        items = getattr(resp, "items", None) or []
        lookup: dict[str, Any] = {}
        for item in items:
            code = getattr(item, "code", None)
            if code:
                lookup[code] = item
    except Exception as exc:
        persist_app_error(exc)
        logger.error("Failed to fetch all Xero items: %s", exc)
        raise
    logger.info("Fetched %d Xero items for lookup", len(lookup))
    return lookup


def generate_item_code(stock_item: Stock) -> str:
    """Generate a valid item code for a stock item based on its properties."""
    if stock_item.item_code and stock_item.item_code.strip():
        return stock_item.item_code.strip()

    parts = []

    # Metal type prefix — keys are MetalType values (apps.job.enums).
    metal_map = {
        "mild_steel": "MS",
        "stainless_steel": "SS",
        "aluminium": "AL",
        "brass": "BR",
        "copper": "CU",
        "titanium": "TI",
        "zinc": "ZN",
        "galvanised": "GAL",
        "other": "OT",
    }

    metal_prefix = metal_map.get(stock_item.metal_type or "", "UN")
    parts.append(metal_prefix)

    if stock_item.alloy and stock_item.alloy.strip():
        parts.append(stock_item.alloy.strip().replace(" ", "").upper()[:6])

    if stock_item.specifics and stock_item.specifics.strip():
        parts.append(stock_item.specifics.strip().replace(" ", "").upper()[:10])

    # If no meaningful parts, use stock ID (shortened)
    if len(parts) == 1 and parts[0] == "UN":
        parts = ["STK", str(stock_item.id)[:8]]

    # Join with hyphens and cap at Xero's 30-character limit.
    return "-".join(parts)[:30]


def validate_stock_for_xero(stock_item: Stock) -> bool:
    """Report whether a stock item is ready for Xero sync."""
    if not stock_item.description or not stock_item.description.strip():
        logger.warning("Stock item %s missing description", stock_item.id)
        return False

    if stock_item.unit_cost is None or stock_item.unit_cost < 0:
        logger.warning(
            "Stock item %s has invalid unit_cost: %s", stock_item.id, stock_item.unit_cost
        )
        return False

    return True


def _ensure_unique_xero_link(
    stock_item: Stock, *, xero_item_id: str, item_code: str | None
) -> bool:
    """Guard against assigning the same Xero item to multiple stock records."""
    code_display = item_code or "<missing>"
    duplicate = Stock.objects.filter(xero_id=xero_item_id).exclude(id=stock_item.id).first()

    if not duplicate:
        return True

    logger.warning(
        "Cannot link stock %s to Xero item %s: stock %s already has this xero_id. "
        "Both have item_code '%s'. This indicates duplicate stock items.",
        stock_item.id,
        xero_item_id,
        duplicate.id,
        code_display,
    )
    return False


def _build_stock_item_payload(
    stock_item: Stock, purchase_account: XeroAccount | None, sales_account: XeroAccount | None
) -> dict[str, Any]:
    """Build a Xero items payload dict from a Stock instance."""
    item_data: dict[str, Any] = {
        "Code": stock_item.item_code,
        "Name": (stock_item.description or "")[:50],
        "Description": stock_item.description,
        "IsTrackedAsInventory": True,
        "QuantityOnHand": float(stock_item.quantity),
    }

    if purchase_account and stock_item.unit_cost is not None:
        item_data["PurchaseDetails"] = {
            "UnitPrice": float(stock_item.unit_cost),
            "AccountCode": purchase_account.account_code,
        }
    else:
        logger.warning("Missing purchase account or unit_cost for stock %s", stock_item.id)

    if stock_item.unit_revenue and stock_item.unit_revenue > 0 and sales_account:
        item_data["SalesDetails"] = {
            "UnitPrice": float(stock_item.unit_revenue),
            "AccountCode": sales_account.account_code,
        }
    else:
        logger.warning(
            "Missing sales account or unit_revenue for stock %s: unit_revenue=%s, sales_account=%s",
            stock_item.id,
            stock_item.unit_revenue,
            sales_account,
        )

    return item_data


def _purchase_account() -> XeroAccount | None:
    return (
        XeroAccount.objects.filter(account_code="300").first()
        or XeroAccount.objects.filter(account_type__in=["EXPENSE", "DIRECTCOSTS"]).first()
    )


def _sales_account() -> XeroAccount | None:
    return (
        XeroAccount.objects.filter(account_code="200").first()
        or XeroAccount.objects.filter(account_type__in=["REVENUE", "OTHERINCOME"]).first()
    )


def sync_all_local_stock_to_xero(  # noqa: C901, PLR0912, PLR0915 -- ported v1 batch loop; link, batch, map-back in one pass
    limit: int | None = None,
) -> dict[str, Any]:
    """Sync all local stock items that don't have a xero_id to Xero.

    Both new items (created in Xero) and items linked-by-Code to existing Xero
    items are pushed via ``update_or_create_items`` in batches of 50 — Xero
    treats payloads with an ``ItemID`` as updates and those without as creates.
    """
    logger.info("Starting sync of local stock items to Xero")

    floor = CompanyDefaults.get_solo().xero_automated_day_floor
    if quota_floor_breached(floor):
        # Raise rather than returning a "0 synced, 0 failed" success-shaped
        # dict — the wrapper in sync.py interprets the dict as success and
        # would let the orchestrator continue to its sync_status:"success"
        # marker, masking the abort.
        raise XeroQuotaFloorReached(f"Skipping local stock sync: Xero day quota at floor ({floor})")

    queryset = Stock.objects.filter(xero_id__isnull=True, is_active=True).order_by("date")

    if limit:
        queryset = queryset[:limit]

    total_items = queryset.count()
    synced_count = 0
    failed_count = 0
    failed_items: list[dict[str, str | None]] = []

    logger.info("Found %d stock items to sync to Xero", total_items)

    api = AccountingApi(get_api_client())
    tenant_id = get_tenant_id()
    xero_items_lookup = fetch_all_xero_items(api, tenant_id)

    purchase_account = _purchase_account()
    sales_account = _sales_account()
    # Missing chart-of-accounts config is an error, not a degraded push:
    # items written without purchase/sales details corrupt the live ledger
    # (ADR 0015 — v1 warned and pushed anyway).
    if purchase_account is None or sales_account is None:
        raise ValueError(
            "Cannot push stock to Xero: no purchase (300/EXPENSE/DIRECTCOSTS) "
            "or sales (200/REVENUE/OTHERINCOME) account found in XeroAccount — "
            "run the accounts sync first"
        )

    # First pass: validate, generate codes, link existing-by-Code. Items linked
    # by Code get an ``ItemID`` set on the payload — the upsert call then
    # pushes data to that item. Items without a match get pushed without an
    # ``ItemID``, and Xero creates them. This pass is DB-only — no API calls.
    items_to_upsert: list[tuple[Stock, dict[str, Any]]] = []

    for stock_item in queryset:
        if not validate_stock_for_xero(stock_item):
            failed_count += 1
            failed_items.append(
                {
                    "id": str(stock_item.id),
                    "description": stock_item.description,
                    "reason": "Validation failed",
                }
            )
            continue

        if not (stock_item.item_code and stock_item.item_code.strip()):
            stock_item.item_code = generate_item_code(stock_item)
            stock_item.save(update_fields=["item_code"])
            logger.info(
                "Generated item_code '%s' for stock %s", stock_item.item_code, stock_item.id
            )

        payload = _build_stock_item_payload(stock_item, purchase_account, sales_account)

        existing = xero_items_lookup.get(stock_item.item_code) if stock_item.item_code else None
        if existing:
            if not _ensure_unique_xero_link(
                stock_item, xero_item_id=existing.item_id, item_code=stock_item.item_code
            ):
                failed_count += 1
                failed_items.append(
                    {
                        "id": str(stock_item.id),
                        "description": stock_item.description,
                        "reason": "Duplicate Code linkage refused",
                    }
                )
                continue

            # Don't persist xero_id yet — if the batched upsert below fails,
            # the row stays in the retry queryset (xero_id__isnull=True).
            payload["ItemID"] = existing.item_id

        items_to_upsert.append((stock_item, payload))

    # Batched upsert: ceil(N/50) API calls. Xero routes by presence of ItemID.
    batch_size = 50
    for i in range(0, len(items_to_upsert), batch_size):
        batch = items_to_upsert[i : i + batch_size]

        floor = CompanyDefaults.get_solo().xero_automated_day_floor
        if quota_floor_breached(floor):
            # Raise rather than logging + breaking. Items already upserted
            # in earlier batches kept their xero_id (set by the post-upsert
            # handler below). Items in remaining batches still have
            # xero_id__isnull=True and will be retried on the next sync.
            # The exception unwinds to the worker task, which emits
            # sync_status:"aborted".
            remaining = len(items_to_upsert) - i
            raise XeroQuotaFloorReached(
                f"Stopping stock upsert with {remaining} un-attempted items: "
                f"Xero day quota at floor ({floor})"
            )

        items_payload = [data for _, data in batch]
        item_by_code = {data["Code"]: stock for stock, data in batch}

        logger.info(
            "Upserting batch of %d stock items in Xero (batch %d)",
            len(items_payload),
            i // batch_size + 1,
        )
        try:
            resp = api.update_or_create_items(tenant_id, items={"Items": items_payload})
            time.sleep(SLEEP_TIME)
        # deliberate-swallow: a failed batch marks its items failed and later
        # batches still get their chance; the rows stay in the retry queryset
        except Exception as exc:  # noqa: BLE001
            persist_app_error(exc)
            logger.error("Failed to upsert batch of %d stock items: %s", len(items_payload), exc)
            for stock_item, _ in batch:
                failed_count += 1
                failed_items.append(
                    {
                        "id": str(stock_item.id),
                        "description": stock_item.description,
                        "reason": f"Batch upsert failed: {exc}",
                    }
                )
            continue

        synced_items = getattr(resp, "items", None) or []
        for synced_item in synced_items:
            code = getattr(synced_item, "code", None)
            matched_stock = item_by_code.get(code)
            if matched_stock is None:
                logger.warning(
                    "Could not map upserted Xero item with code '%s' back to local stock", code
                )
                continue
            matched_stock.xero_id = synced_item.item_id
            matched_stock.xero_last_modified = timezone.now()
            matched_stock.xero_last_synced = timezone.now()
            matched_stock.save(update_fields=["xero_id", "xero_last_modified", "xero_last_synced"])
            synced_count += 1
            logger.info(
                "Upserted stock item %s in Xero with ID %s", matched_stock.id, matched_stock.xero_id
            )

    # Clamp success_rate to 0-100 range for valid progress bar display
    raw_rate = (synced_count / total_items * 100) if total_items > 0 else 0
    success_rate = max(0, min(100, raw_rate))

    result: dict[str, Any] = {
        "total_items": total_items,
        "synced_count": synced_count,
        "failed_count": failed_count,
        "failed_items": failed_items,
        "success_rate": success_rate,
    }

    if total_items == 0:
        logger.info("No stock items needed syncing to Xero (all items already have xero_id)")
    else:
        logger.info(
            "Completed stock sync: %d/%d successful (%.1f%%)",
            synced_count,
            total_items,
            success_rate,
        )

    return result
