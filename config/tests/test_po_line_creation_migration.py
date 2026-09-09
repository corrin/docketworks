"""Adding creation times backfills historical PO lines rather than leaving them unknown."""

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from apps.purchasing.models import PurchaseOrderLine
from apps.purchasing.tests.factories import make_purchase_order

pytestmark = pytest.mark.django_db


def test_legacy_lines_are_backfilled_and_keep_every_other_value() -> None:
    """A line predating the column gets its order's creation time, not a NULL and not today.

    ADR 0059: an approximate time every reader can sort by beats an accurate absence every
    reader must special-case, so the assertion is that nothing is left unknown.
    """
    old = ("purchasing", "0015_backfill_legacy_receipt_evidence")
    new = ("purchasing", "0016_alter_purchaseorderline_options_and_more")
    executor = MigrationExecutor(connection)
    executor.migrate([old])
    historical = executor.loader.project_state([old]).apps.get_model(
        "purchasing", "PurchaseOrderLine"
    )
    po = make_purchase_order()
    line = historical.objects.create(
        purchase_order_id=po.id,
        description="Historical line",
        quantity=3,
        unit_cost=12,
    )
    before = historical.objects.values().get(pk=line.pk)
    # ADR 0048: validate deferred FKs before transactional DDL; rollback owns cleanup.
    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
    MigrationExecutor(connection).migrate([new])
    after = PurchaseOrderLine.objects.values().get(pk=line.pk)
    assert after["created_at"] == po.created_at
    assert PurchaseOrderLine.objects.values(*before).get(pk=line.pk) == before
    fresh = PurchaseOrderLine.objects.create(
        purchase_order=po,
        description="New line",
        quantity=1,
        unit_cost=4,
    )
    assert fresh.created_at > po.created_at
    assert list(po.po_lines.values_list("id", flat=True)) == [line.pk, fresh.pk]
