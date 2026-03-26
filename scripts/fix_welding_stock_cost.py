"""
Fix unit cost on the 'Welding' stock item (STK-5f0d0b6f).

Currently $0.00 cost / $12.00 revenue per lineal metre.
Sets cost to $6.00/m based on typical welding consumable costs (gas, wire, tips).
Syncs the change to Xero.

Usage:
    python manage.py shell < scripts/fix_welding_stock_cost.py
    DRY_RUN=false python manage.py shell < scripts/fix_welding_stock_cost.py
"""

import logging
import os
from decimal import Decimal

from django.db import transaction

from apps.purchasing.models import Stock
from apps.workflow.api.xero.stock_sync import sync_stock_to_xero

logger = logging.getLogger(__name__)

DRY_RUN = os.environ.get("DRY_RUN", "true").lower() != "false"
ITEM_CODE = "STK-5f0d0b6f"
NEW_UNIT_COST = Decimal("6.00")

logger.info(
    "%s: Updating unit cost for %s", "DRY RUN" if DRY_RUN else "LIVE RUN", ITEM_CODE
)
logger.info("=" * 60)

try:
    with transaction.atomic():
        stock = Stock.objects.select_for_update().get(item_code=ITEM_CODE)

        logger.info("Item:        %s", stock.item_code)
        logger.info("Description: %s", stock.description)
        logger.info("Xero ID:     %s", stock.xero_id)
        logger.info("Current cost:    $%s", stock.unit_cost)
        logger.info("Current revenue: $%s", stock.unit_revenue)
        logger.info("New cost:        $%s", NEW_UNIT_COST)

        if stock.unit_cost != Decimal("0.00"):
            logger.warning(
                "unit_cost is not $0.00 (it's $%s). Aborting.", stock.unit_cost
            )
            raise RuntimeError("Unexpected current cost - aborting for safety")

        stock.unit_cost = NEW_UNIT_COST
        stock.save(update_fields=["unit_cost"])
        logger.info("Database updated.")

        if DRY_RUN:
            logger.info("DRY RUN - rolling back. No Xero sync.")
            raise RuntimeError("DRY RUN rollback")

        # Sync to Xero
        logger.info("Syncing to Xero...")
        success = sync_stock_to_xero(stock)
        if success:
            logger.info("Xero sync successful.")
        else:
            logger.error(
                "Xero sync failed. Database change is committed but Xero is out of sync."
            )

except RuntimeError as e:
    if "DRY RUN rollback" in str(e):
        logger.info("No changes made.")
    else:
        raise
