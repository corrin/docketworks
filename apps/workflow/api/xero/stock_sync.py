import logging
import time
from typing import Any, Dict, Optional

from django.db import models
from django.utils import timezone
from xero_python.accounting import AccountingApi

from apps.purchasing.models import Stock
from apps.workflow.api.xero.auth import api_client, get_tenant_id
from apps.workflow.models import XeroAccount

logger = logging.getLogger("xero")
SLEEP_TIME = 1  # Sleep after every API call to avoid hitting rate limits


def fetch_all_xero_items(api: AccountingApi, tenant_id: str) -> Dict[str, Any]:
    """Fetch all Xero items and return a code -> item lookup dictionary.

    This is more efficient than per-item queries and handles special characters
    in codes that can't be escaped in WHERE clauses (e.g., double quotes).
    """
    try:
        resp = api.get_items(tenant_id)
        time.sleep(SLEEP_TIME)
        items = getattr(resp, "items", None) or getattr(resp, "Items", None) or []
        lookup = {}
        for item in items:
            code = getattr(item, "code", None)
            if code:
                lookup[code] = item
        logger.info(f"Fetched {len(lookup)} Xero items for lookup")
        return lookup
    except Exception as e:
        logger.error(f"Failed to fetch all Xero items: {e}")
        raise


def get_xero_item_by_code_from_lookup(
    code: str, xero_items_lookup: Dict[str, Any]
) -> Optional[Any]:
    """Look up a Xero item by code using pre-fetched lookup dictionary."""
    if not code:
        return None
    return xero_items_lookup.get(code)


def generate_item_code(stock_item: Stock) -> str:
    """
    Generate a valid item code for a stock item based on its properties.

    Args:
        stock_item: Stock instance to generate code for

    Returns:
        str: Generated item code
    """
    # Try to use parsed item_code first
    if stock_item.item_code and stock_item.item_code.strip():
        return stock_item.item_code.strip()

    # Generate based on metal type, alloy, and specifics
    parts = []

    # Metal type prefix
    # Should ALWAYS be based on MetalType (apps.job.enums)
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
        "unspecified": "UN",
    }

    metal_prefix = metal_map.get(stock_item.metal_type, "UN")
    parts.append(metal_prefix)

    # Add alloy if available
    if stock_item.alloy and stock_item.alloy.strip():
        alloy_clean = stock_item.alloy.strip().replace(" ", "").upper()[:6]
        parts.append(alloy_clean)

    # Add specifics if available (truncated)
    if stock_item.specifics and stock_item.specifics.strip():
        specifics_clean = stock_item.specifics.strip().replace(" ", "").upper()[:10]
        parts.append(specifics_clean)

    # If no meaningful parts, use stock ID (shortened)
    if len(parts) == 1 and parts[0] == "UN":
        parts = ["STK", str(stock_item.id)[:8]]

    # Join with hyphens and ensure max length (Xero limit is 30 characters)
    item_code = "-".join(parts)[:30]

    return item_code


def validate_stock_for_xero(stock_item: Stock) -> bool:
    """
    Validate if a stock item is ready for Xero sync.

    Args:
        stock_item: Stock instance to validate

    Returns:
        bool: True if valid for sync
    """
    if not stock_item.description or not stock_item.description.strip():
        logger.warning(f"Stock item {stock_item.id} missing description")
        return False

    if stock_item.unit_cost is None or stock_item.unit_cost < 0:
        logger.warning(
            f"Stock item {stock_item.id} has invalid unit_cost: {stock_item.unit_cost}"
        )
        return False

    return True


def _ensure_unique_xero_link(
    stock_item: Stock,
    *,
    xero_item_id: str,
    item_code: Optional[str],
    operation: str,
) -> bool:
    """
    Guard against assigning the same Xero item to multiple stock records.
    """
    code_display = item_code or "<missing>"
    duplicate = (
        Stock.objects.filter(xero_id=xero_item_id).exclude(id=stock_item.id).first()
    )

    if not duplicate:
        return True

    message = (
        f"Cannot link stock {stock_item.id} to Xero item {xero_item_id}: "
        f"stock {duplicate.id} already has this xero_id. "
        f"Both have item_code '{code_display}'. This indicates duplicate stock items."
    )
    logger.warning(message)
    return False


def sync_stock_to_xero(
    stock_item: Stock, xero_items_lookup: Optional[Dict[str, Any]] = None
) -> bool:
    """
    Push a stock item to Xero as an inventory item.

    Args:
        stock_item: Stock instance to sync
        xero_items_lookup: Pre-fetched dict of code -> Xero item for efficient lookup.
                          If None, will be fetched (less efficient for batch operations).

    Returns:
        bool: True if successful
    """
    # Initial validation to fail fast
    if not validate_stock_for_xero(stock_item):
        logger.error(f"Stock item {stock_item.id} failed validation for Xero sync")
        return False

    if not (stock_item.item_code and stock_item.item_code.strip()):
        stock_item.item_code = generate_item_code(stock_item)
        stock_item.save(update_fields=["item_code"])
        logger.info(
            f"Generated item_code '{stock_item.item_code}' for stock {stock_item.id}"
        )

    api = AccountingApi(api_client)
    tenant_id = get_tenant_id()

    purchase_account = (
        XeroAccount.objects.filter(account_code="300").first()
        or XeroAccount.objects.filter(
            account_type__in=["EXPENSE", "DIRECTCOSTS"]
        ).first()
    )
    sales_account = (
        XeroAccount.objects.filter(account_code="200").first()
        or XeroAccount.objects.filter(
            account_type__in=["REVENUE", "OTHERINCOME"]
        ).first()
    )

    item_data = {
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
        logger.warning(
            f"Missing purchase account or unit_cost for stock {stock_item.id}"
        )

    if stock_item.unit_revenue and stock_item.unit_revenue > 0 and sales_account:
        item_data["SalesDetails"] = {
            "UnitPrice": float(stock_item.unit_revenue),
            "AccountCode": sales_account.account_code,
        }
    else:
        logger.warning(
            f"Missing sales account or unit_revenue for stock {stock_item.id}: "
            f"unit_revenue={stock_item.unit_revenue}, sales_account={sales_account}"
        )

    logger.info(f"Sending item data to Xero: {item_data}")

    # Fetch lookup if not provided (less efficient for batch operations)
    if xero_items_lookup is None:
        xero_items_lookup = fetch_all_xero_items(api, tenant_id)

    try:
        # 1) If we don't have xero_id, try to find by Code first
        if not stock_item.xero_id:
            existing = get_xero_item_by_code_from_lookup(
                stock_item.item_code, xero_items_lookup
            )
            if existing:
                if not _ensure_unique_xero_link(
                    stock_item,
                    xero_item_id=existing.item_id,
                    item_code=stock_item.item_code,
                    operation="sync_stock_to_xero_duplicate_check",
                ):
                    return False

                stock_item.xero_id = existing.item_id
                stock_item.xero_last_modified = timezone.now()
                stock_item.xero_last_synced = timezone.now()
                stock_item.save(
                    update_fields=["xero_id", "xero_last_modified", "xero_last_synced"]
                )
                logger.info(
                    f"Linked local stock {stock_item.id} to existing Xero item {stock_item.xero_id} by Code"
                )

        # 2) If we already have xero_id -> update; else -> create
        if stock_item.xero_id:
            item_data["ItemID"] = stock_item.xero_id
            api.update_item(
                tenant_id, item_id=stock_item.xero_id, items={"Items": [item_data]}
            )
            time.sleep(SLEEP_TIME)
            stock_item.xero_last_synced = timezone.now()
            stock_item.save(update_fields=["xero_last_synced"])
            logger.info(f"Updated stock item {stock_item.id} in Xero")
            return True

        # Still no xero_id → create
        resp = api.create_items(tenant_id, items={"Items": [item_data]})
        time.sleep(SLEEP_TIME)

        created = getattr(resp, "items", None) or getattr(resp, "Items", None) or []
        if not created:
            logger.error("Xero create_items returned empty response")
            return False

        xero_item = created[0]
        stock_item.xero_id = xero_item.item_id
        stock_item.xero_last_modified = timezone.now()
        stock_item.xero_last_synced = timezone.now()
        stock_item.save(
            update_fields=["xero_id", "xero_last_modified", "xero_last_synced"]
        )
        logger.info(
            f"Created stock item {stock_item.id} in Xero with ID {stock_item.xero_id}"
        )
        return True

    except Exception as e:
        msg = str(e)

        # 3) If error is "already exists" by Code, refresh lookup and try to link
        # Note: this should be rare due to the initial lookup by Code above
        if "already exists" in msg and "Code" in msg:
            logger.warning(
                f"Create failed due to duplicate Code. Refreshing lookup for {stock_item.item_code}"
            )
            # Refresh the lookup in case item was created since we fetched
            xero_items_lookup = fetch_all_xero_items(api, tenant_id)
            existing = get_xero_item_by_code_from_lookup(
                stock_item.item_code, xero_items_lookup
            )
            if not existing:
                logger.error(
                    f"Duplicate reported for code '{stock_item.item_code}', "
                    f"but item not found in refreshed lookup — aborting"
                )
                return False

            if not _ensure_unique_xero_link(
                stock_item,
                xero_item_id=existing.item_id,
                item_code=stock_item.item_code,
                operation="sync_stock_to_xero_duplicate_recovery",
            ):
                return False

            stock_item.xero_id = existing.item_id
            stock_item.xero_last_modified = timezone.now()
            stock_item.xero_last_synced = timezone.now()
            stock_item.save(
                update_fields=["xero_id", "xero_last_modified", "xero_last_synced"]
            )

            try:
                item_data["ItemID"] = stock_item.xero_id
                api.update_item(
                    tenant_id, item_id=stock_item.xero_id, items={"Items": [item_data]}
                )
                time.sleep(SLEEP_TIME)
                logger.info(
                    f"Recovered by linking and updating stock item {stock_item.id} -> Xero {stock_item.xero_id}"
                )
                return True
            except Exception as e2:
                logger.error(f"Failed to update after linking by Code: {e2}")
                return False

        # Other errors: log and fail
        logger.error(f"Failed to sync stock item {stock_item.id} to Xero: {msg}")
        return False


def sync_all_local_stock_to_xero(limit: Optional[int] = None) -> Dict[str, Any]:
    """
    Sync all local stock items that don't have xero_id to Xero.

    Args:
        limit: Optional limit on number of items to sync

    Returns:
        Dict with sync results
    """
    logger.info("Starting sync of local stock items to Xero")

    # Get stock items that need syncing (no xero_id and active)
    queryset = Stock.objects.filter(xero_id__isnull=True, is_active=True).order_by(
        "date"
    )

    if limit:
        queryset = queryset[:limit]

    total_items = queryset.count()
    synced_count = 0
    failed_count = 0
    failed_items = []

    logger.info(f"Found {total_items} stock items to sync to Xero")

    # Fetch all Xero items once for efficient lookup
    api = AccountingApi(api_client)
    tenant_id = get_tenant_id()
    xero_items_lookup = fetch_all_xero_items(api, tenant_id)

    for stock_item in queryset:
        try:
            if sync_stock_to_xero(stock_item, xero_items_lookup):
                synced_count += 1
                logger.info(f"Successfully synced stock item {stock_item.id}")
            else:
                failed_count += 1
                failed_items.append(
                    {
                        "id": str(stock_item.id),
                        "description": stock_item.description,
                        "reason": "Validation failed or API error",
                    }
                )
                logger.warning(f"Failed to sync stock item {stock_item.id}")
        except Exception as e:
            failed_count += 1
            failed_items.append(
                {
                    "id": str(stock_item.id),
                    "description": stock_item.description,
                    "reason": str(e),
                }
            )
            logger.error(f"Exception syncing stock item {stock_item.id}: {str(e)}")

    # Clamp success_rate to 0-100 range for valid progress bar display
    raw_rate = (synced_count / total_items * 100) if total_items > 0 else 0
    success_rate = max(0, min(100, raw_rate))

    result = {
        "total_items": total_items,
        "synced_count": synced_count,
        "failed_count": failed_count,
        "failed_items": failed_items,
        "success_rate": success_rate,
    }

    if total_items == 0:
        logger.info(
            "No stock items needed syncing to Xero (all items already have xero_id)"
        )
    else:
        logger.info(
            f"Completed stock sync: {synced_count}/{total_items} successful ({result['success_rate']:.1f}%)"
        )

    return result


def update_stock_item_codes():
    """
    Update item_code for existing stock items that don't have one or have invalid ones.
    This is a utility function to fix existing data.
    """
    logger.info("Starting update of missing/invalid item codes for stock items")

    # Find items with missing codes OR codes that are too long (>30 chars)
    stock_items = Stock.objects.filter(
        models.Q(item_code__isnull=True)
        | models.Q(item_code="")
        | models.Q(item_code__regex=r"^.{31,}$"),  # More than 30 characters
        is_active=True,
    )

    updated_count = 0

    for stock_item in stock_items:
        try:
            old_code = stock_item.item_code
            new_code = generate_item_code(stock_item)

            # Only update if the new code is different and valid
            if new_code != old_code and len(new_code) <= 30:
                stock_item.item_code = new_code
                stock_item.save(update_fields=["item_code"])
                updated_count += 1
                logger.info(
                    f"Updated stock {stock_item.id} item_code: '{old_code}' -> '{new_code}'"
                )
            elif len(new_code) > 30:
                logger.warning(
                    f"Generated code too long for stock {stock_item.id}: '{new_code}' ({len(new_code)} chars)"
                )

        except Exception as e:
            logger.error(
                f"Failed to update item_code for stock {stock_item.id}: {str(e)}"
            )

    logger.info(f"Updated item_code for {updated_count} stock items")
    return updated_count


def fix_long_item_codes():
    """
    Specifically fix item codes that are too long for Xero (>30 characters).
    """
    logger.info("Starting fix of long item codes for stock items")

    # Find items with codes longer than 30 characters
    long_code_items = Stock.objects.filter(
        item_code__regex=r"^.{31,}$", is_active=True  # More than 30 characters
    )

    fixed_count = 0

    for stock_item in long_code_items:
        try:
            old_code = stock_item.item_code

            # If it's a stock-{uuid} pattern, shorten it
            if old_code and old_code.startswith("stock-"):
                # Extract UUID and shorten
                uuid_part = old_code.replace("stock-", "")[:8]
                new_code = f"STK-{uuid_part}"
            else:
                # Use the standard generation logic
                new_code = generate_item_code(stock_item)

            # Ensure it's not too long
            if len(new_code) > 30:
                # Truncate if still too long
                new_code = new_code[:30]

            stock_item.item_code = new_code
            stock_item.save(update_fields=["item_code"])
            fixed_count += 1
            logger.info(
                f"Fixed long item_code for stock {stock_item.id}: '{old_code}' -> '{new_code}'"
            )

        except Exception as e:
            logger.error(
                f"Failed to fix long item_code for stock {stock_item.id}: {str(e)}"
            )

    logger.info(f"Fixed {fixed_count} long item codes")
    return fixed_count
