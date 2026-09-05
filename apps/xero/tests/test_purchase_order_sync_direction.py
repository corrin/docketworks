"""Purchase-order sync runs both ways, and neither direction is dropped.

An order edited in Xero flows in, because an edit made there has to land
somewhere. The one exception is a real collision — we hold a change Xero has
not seen — and it is resolved rather than ignored: the older copy does not
overwrite the newer edit, and ours is published instead.

Business risk covered. The hourly sync used to upsert PO lines straight from
Xero with no regard for whether our own edit had been sent, so a price confirmed
when the bill arrived was reverted at the top of the hour. Separately, Xero's
BILLED status set `fully_received` locally, marking material as received that
nobody had receipted — orders with no stock row and no cost line, which is cost
that never reaches a job (KAN-144). The second is a semantic fault rather than a
direction one: being invoiced is not a claim that goods arrived, whichever way
the data flows.
"""

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from django.utils import timezone

from apps.accounts.models import Staff
from apps.company.models import Company
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLine
from apps.xero.transforms import transform_purchase_order

pytestmark = pytest.mark.django_db

PUSH = "apps.xero.transforms.queue_purchase_order_push"


@pytest.fixture
def supplier() -> Company:
    return Company.objects.create(
        name="Ownership Supplier",
        xero_contact_id=str(uuid4()),
        xero_last_modified=timezone.now(),
    )


def _incoming(supplier: Company, po_number: str, status: str) -> SimpleNamespace:
    """A Xero purchase order carrying a line that differs from ours."""
    return SimpleNamespace(
        contact=SimpleNamespace(contact_id=supplier.xero_contact_id, name=supplier.name),
        purchase_order_number=po_number,
        date="2026-05-05",
        status=status,
        updated_date_utc=datetime(2026, 5, 5, tzinfo=UTC),
        delivery_date=None,
        line_items=[
            SimpleNamespace(
                description="Xero's idea of the line",
                quantity=Decimal("99"),
                unit_amount=Decimal("1.00"),
                item_code=None,
                line_item_id=str(uuid4()),
            )
        ],
    )


def _sent_order(
    supplier: Company,
    *,
    xero_id: UUID,
    status: str = "submitted",
    dw_raised: bool = True,
) -> PurchaseOrder:
    """An order already published to Xero, with nothing outstanding to send."""
    po = PurchaseOrder.objects.create(
        supplier=supplier,
        created_by=Staff.get_automation_user() if dw_raised else None,
        status=status,
        po_number=f"PO-SYNC-{uuid4().hex[:6]}",
        xero_id=xero_id,
    )
    PurchaseOrderLine.objects.create(
        purchase_order=po,
        description="What we ordered",
        quantity=Decimal("4.00"),
        unit_cost=Decimal("12.50"),
    )
    # Sent after the last edit: nothing outstanding.
    PurchaseOrder.objects.filter(id=po.id).update(xero_last_pushed=timezone.now())
    po.refresh_from_db()
    return po


class TestXerosDirection:
    """An edit made in Xero lands here. That direction is not dropped."""

    def test_a_line_edited_in_xero_flows_in(self, supplier: Company) -> None:
        xero_id = uuid4()
        po = _sent_order(supplier, xero_id=xero_id)

        transform_purchase_order(_incoming(supplier, po.po_number, "SUBMITTED"), xero_id)

        line = po.po_lines.get(description="Xero's idea of the line")
        assert line.quantity == Decimal("99")

    def test_a_status_change_in_xero_flows_in(self, supplier: Company) -> None:
        xero_id = uuid4()
        po = _sent_order(supplier, xero_id=xero_id, status="draft")

        transform_purchase_order(_incoming(supplier, po.po_number, "SUBMITTED"), xero_id)

        po.refresh_from_db()
        assert po.status == "submitted"

    def test_a_void_in_xero_flows_in(self, supplier: Company) -> None:
        xero_id = uuid4()
        po = _sent_order(supplier, xero_id=xero_id)

        transform_purchase_order(_incoming(supplier, po.po_number, "VOIDED"), xero_id)

        po.refresh_from_db()
        assert po.status == "deleted"
        assert po.xero_status == "VOIDED"


class TestACollision:
    """We hold an edit Xero has not seen. Resolved, not ignored."""

    def test_xeros_older_copy_does_not_revert_our_unsent_edit(self, supplier: Company) -> None:
        """The confirmed price survives the hour."""
        xero_id = uuid4()
        po = _sent_order(supplier, xero_id=xero_id)
        # Edited after the last successful send: our copy is the newer one.
        PurchaseOrder.objects.filter(id=po.id).update(updated_at=timezone.now())

        with patch(PUSH) as push:
            transform_purchase_order(_incoming(supplier, po.po_number, "SUBMITTED"), xero_id)

        line = po.po_lines.get()
        assert line.description == "What we ordered"
        assert line.quantity == Decimal("4.00")
        assert line.unit_cost == Decimal("12.50")
        push.assert_called_once()

    def test_the_collision_publishes_ours_rather_than_dropping_either(
        self, supplier: Company
    ) -> None:
        """Both directions handled: theirs is refused, ours is sent."""
        xero_id = uuid4()
        po = _sent_order(supplier, xero_id=xero_id)
        PurchaseOrder.objects.filter(id=po.id).update(updated_at=timezone.now())

        with patch(PUSH) as push:
            transform_purchase_order(_incoming(supplier, po.po_number, "SUBMITTED"), xero_id)

        assert push.call_args.args[0].id == po.id

    def test_an_order_that_arrived_from_xero_never_collides(self, supplier: Company) -> None:
        """We never hold an unsent edit for one we do not publish."""
        xero_id = uuid4()
        po = _sent_order(supplier, xero_id=xero_id, dw_raised=False)
        PurchaseOrder.objects.filter(id=po.id).update(updated_at=timezone.now())

        transform_purchase_order(_incoming(supplier, po.po_number, "SUBMITTED"), xero_id)

        assert po.po_lines.get(description="Xero's idea of the line").quantity == Decimal("99")


class TestBilledIsNotReceived:
    """A semantic fault, true in either direction."""

    def test_billed_records_xeros_word_without_asserting_delivery(self, supplier: Company) -> None:
        xero_id = uuid4()
        po = _sent_order(supplier, xero_id=xero_id)

        transform_purchase_order(_incoming(supplier, po.po_number, "BILLED"), xero_id)

        po.refresh_from_db()
        assert po.xero_status == "BILLED"
        assert po.status == "submitted", "Xero marked goods received that nobody receipted"
        assert not po.po_lines.filter(received_quantity__gt=0).exists()
