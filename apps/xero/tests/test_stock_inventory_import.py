"""Catalogue refreshes must preserve local stocktake and receipt evidence."""

from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.utils import timezone
from xero_python.accounting import Item, Purchase

from apps.job.models import Job
from apps.purchasing.models import Stock, StockMovementKind
from apps.purchasing.services.stock_movement_service import (
    MovementContext,
    inventory_difference,
    move_stock,
)
from apps.purchasing.tests.factories import make_stock
from apps.xero import transforms

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("existing", [False, True])
def test_catalogue_refresh_preserves_local_inventory(
    stock_holding_job: Job, existing: bool
) -> None:
    xero_id = uuid4()
    item = Item(
        code="STEEL-06",
        name="0.6mm sheet",
        is_tracked_as_inventory=True,
        quantity_on_hand=99,
        updated_date_utc=timezone.now(),
        purchase_details=Purchase(unit_price=200),
        sales_details=Purchase(unit_price=250),
    )
    if existing:
        stock = make_stock(stock_holding_job, quantity="0", unit_cost="80")
        stock.xero_id = str(xero_id)
        stock.save(update_fields=["xero_id"])
        move_stock(
            stock, Decimal("1"), MovementContext(kind=StockMovementKind.RECEIPT, reason="Receipt")
        )
    original_apply = transforms._track_and_apply_changes

    def apply_with_intervening_receipt(instance: Stock, fields: dict[str, object]) -> list[str]:
        changed = original_apply(instance, fields)
        if existing:
            other = Stock.objects.get(pk=instance.pk)
            move_stock(
                other,
                Decimal("1"),
                MovementContext(kind=StockMovementKind.RECEIPT, reason="Delivery"),
            )
        return changed

    with (
        patch.object(transforms, "_track_and_apply_changes", apply_with_intervening_receipt),
        patch.object(transforms, "enqueue_stock_metadata_parse"),
    ):
        imported, _ = transforms.transform_stock(item, xero_id)
    imported.refresh_from_db()
    assert imported.description == "0.6mm sheet"
    assert inventory_difference(imported) == 0
    if existing:
        assert imported.quantity == Decimal("2")
        assert imported.unit_cost == Decimal("80")
        assert imported.source == "manual"
    else:
        assert imported.quantity == 0
        assert imported.unit_cost == Decimal("200")
        assert imported.source == "product_catalog"
