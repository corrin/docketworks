"""Restored orders Xero refuses are repaired once, by migration (ADR 0059)."""

from datetime import date
from importlib import import_module

import pytest
from django.db import connection, transaction

from apps.job.models import Job
from apps.purchasing.models import PurchaseOrder
from apps.purchasing.tests.factories import make_po_line, make_purchase_order, make_stock

pytestmark = pytest.mark.django_db


def apply_repair() -> None:
    """Execute the forward data migration against historical fixture rows."""
    migration = import_module("apps.purchasing.migrations.0021_order_lines_and_dates_xero_refuses")
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(migration.BLANK_UNKNOWN_ITEM_CODES_SQL)
        cursor.execute(migration.RESTORE_CENTURY_SQL)


def test_a_code_no_stock_item_carries_is_blanked_and_a_known_one_kept(
    stock_holding_job: Job,
) -> None:
    make_stock(stock_holding_job, item_code="SHEET-16")
    order = make_purchase_order()
    unknown = make_po_line(order, description="1.6mm sheet", item_code="P0035743 16EGS")
    known = make_po_line(order, item_code="SHEET-16")
    free_text = make_po_line(order, description="Freight")

    apply_repair()

    unknown.refresh_from_db()
    known.refresh_from_db()
    free_text.refresh_from_db()
    # Still the same line: only the code Xero would refuse is gone.
    assert (unknown.item_code, unknown.description) == (None, "1.6mm sheet")
    assert known.item_code == "SHEET-16"
    assert free_text.item_code is None


def test_a_two_digit_year_gets_its_century_back_and_a_real_date_is_left() -> None:
    typo = make_purchase_order()
    sound = make_purchase_order()
    unset = make_purchase_order()
    PurchaseOrder.objects.filter(id=typo.id).update(expected_delivery=date(25, 8, 20))
    PurchaseOrder.objects.filter(id=sound.id).update(expected_delivery=date(2025, 8, 20))

    apply_repair()

    typo.refresh_from_db()
    sound.refresh_from_db()
    unset.refresh_from_db()
    assert typo.expected_delivery == date(2025, 8, 20)
    assert sound.expected_delivery == date(2025, 8, 20)
    assert unset.expected_delivery is None
