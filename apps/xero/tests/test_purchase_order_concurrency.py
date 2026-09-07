"""An inbound Xero save must wait for the receipt transaction before reading its state."""

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from queue import Queue
from time import monotonic, sleep
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.db import connection, connections, transaction
from django.utils import timezone
from pytest_django.plugin import DjangoDbBlocker

from apps.company.models import Company
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLine
from apps.purchasing.services.allocation_service import recompute_purchase_order_status
from apps.xero.transforms import transform_purchase_order


@pytest.mark.parametrize("received", [Decimal("1"), Decimal("2")])
@pytest.mark.usefixtures("django_db_setup")
def test_sync_waits_for_receipt_and_preserves_its_committed_status(
    django_db_blocker: DjangoDbBlocker, received: Decimal
) -> None:
    """Real connections reproduce a stale save overwriting a newly committed receipt."""
    with django_db_blocker.unblock():
        supplier = Company.objects.create(
            name=f"Concurrency supplier {uuid4()}",
            xero_contact_id=str(uuid4()),
            xero_last_modified=timezone.now(),
        )
        po = PurchaseOrder.objects.create(
            supplier=supplier,
            po_number=f"TEST-{uuid4()}",
            xero_id=uuid4(),
            status="submitted",
        )
        line = PurchaseOrderLine.objects.create(
            purchase_order=po,
            description="Received bar",
            quantity=2,
            unit_cost=10,
        )
        PurchaseOrder.objects.filter(pk=po.id).update(xero_agreed_at=timezone.now())
        incoming = SimpleNamespace(
            contact=SimpleNamespace(contact_id=supplier.xero_contact_id, name=supplier.name),
            purchase_order_number=po.po_number,
            date="2026-05-05",
            status="VOIDED",
            updated_date_utc=timezone.now(),
            delivery_date=None,
            line_items=[],
        )
        backend_pids: Queue[int] = Queue()

        def sync() -> str:
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_backend_pid()")
                    backend_pids.put(cursor.fetchone()[0])
                result, _status = transform_purchase_order(incoming, str(po.xero_id))
                return result.status
            finally:
                connections.close_all()

        try:
            with (
                patch("apps.xero.transforms.queue_purchase_order_push"),
                ThreadPoolExecutor(max_workers=1) as pool,
            ):
                with transaction.atomic():
                    locked = PurchaseOrder.objects.select_for_update().get(pk=po.id)
                    PurchaseOrderLine.objects.filter(pk=line.id).update(received_quantity=received)
                    recompute_purchase_order_status(locked)
                    # GPT: the receipt is now uncommitted. An unlocked importer reads
                    # the old status, waits at save, then overwrites the receipt on commit.
                    pending = pool.submit(sync)
                    backend_pid = backend_pids.get(timeout=10)
                    deadline = monotonic() + 10
                    while True:
                        with connection.cursor() as cursor:
                            cursor.execute(
                                "SELECT cardinality(pg_blocking_pids(%s))", [backend_pid]
                            )
                            if cursor.fetchone()[0] > 0:
                                break
                        if pending.done() or monotonic() >= deadline:
                            raise AssertionError(
                                "The importer did not wait for the receipt transaction"
                            )
                        sleep(0.01)
                expected = "partially_received" if received == 1 else "fully_received"
                assert pending.result(timeout=10) == expected
            po.refresh_from_db()
            line.refresh_from_db()
            assert po.status == expected
            assert line.received_quantity == received
        finally:
            PurchaseOrderLine.objects.filter(purchase_order=po).delete()
            po.delete()
            supplier.delete()
