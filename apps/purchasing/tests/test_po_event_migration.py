"""Migration 0020: every PO note survives the move into the shared audit shape.

Guards the RunPython step between the add and remove operations: dropping it,
or reordering RemoveField ahead of it, loses the three production notes.
"""

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

from apps.accounts.models import Staff
from apps.purchasing.models import PurchaseOrderEvent
from apps.purchasing.tests.factories import make_purchase_order

pytestmark = pytest.mark.django_db

BEFORE = ("purchasing", "0019_purchaseorder_created_by_not_null")


def test_a_note_written_into_description_reads_back_as_a_manual_note(
    office_staff: Staff,
) -> None:
    po = make_purchase_order()
    with connection.cursor() as cursor:
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
    executor = MigrationExecutor(connection)
    executor.migrate([BEFORE])
    legacy_event_model = executor.loader.project_state(BEFORE).apps.get_model(
        "purchasing", "PurchaseOrderEvent"
    )
    legacy = legacy_event_model.objects.create(
        purchase_order_id=po.id, staff_id=office_staff.id, description="Chased the supplier"
    )

    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())

    migrated = PurchaseOrderEvent.objects.get(id=legacy.id)
    assert migrated.event_type == "manual_note"
    assert migrated.detail == {"note_text": "Chased the supplier"}
    assert migrated.description == "Chased the supplier"
