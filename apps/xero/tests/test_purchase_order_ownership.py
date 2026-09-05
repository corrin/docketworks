"""The purchase order has one owner, and it is Docketworks.

Xero holds a copy so the supplier's bill has something to reconcile against.
That copy is a reader, not a writer: an order raised here keeps its own lines,
its own prices and its own receiving state, whatever Xero later says about it.

Business risk covered. Before this rule, the hourly sync upserted PO lines
straight from Xero, so a price confirmed when the bill arrived was reverted at
the top of the hour — and Xero's BILLED status set `fully_received` locally,
marking material as received that nobody had receipted. That second one leaves
purchase orders with no stock row and no cost line, which is cost that never
reaches a job (KAN-144).
"""

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from django.utils import timezone

from apps.accounts.models import Staff
from apps.company.models import Company
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLine
from apps.xero.transforms import transform_purchase_order

pytestmark = pytest.mark.django_db


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


def _our_order(
    supplier: Company, *, created_by: Staff | None, status: str, xero_id: UUID
) -> PurchaseOrder:
    po = PurchaseOrder.objects.create(
        supplier=supplier,
        created_by=created_by,
        status=status,
        po_number=f"PO-OWN-{uuid4().hex[:6]}",
        xero_id=xero_id,
    )
    PurchaseOrderLine.objects.create(
        purchase_order=po,
        description="What we ordered",
        quantity=Decimal("4.00"),
        unit_cost=Decimal("12.50"),
    )
    return po


class TestDocketworksOwnedOrders:
    def test_the_sync_does_not_rewrite_our_lines(self, supplier: Company) -> None:
        """The confirmed price survives the hour."""
        xero_id = uuid4()
        po = _our_order(
            supplier, created_by=Staff.get_automation_user(), status="submitted", xero_id=xero_id
        )

        transform_purchase_order(_incoming(supplier, po.po_number, "SUBMITTED"), xero_id)

        line = po.po_lines.get()
        assert line.description == "What we ordered"
        assert line.quantity == Decimal("4.00")
        assert line.unit_cost == Decimal("12.50")

    def test_the_sync_does_not_rewrite_our_receiving_state(self, supplier: Company) -> None:
        xero_id = uuid4()
        po = _our_order(
            supplier,
            created_by=Staff.get_automation_user(),
            status="fully_received",
            xero_id=xero_id,
        )

        transform_purchase_order(_incoming(supplier, po.po_number, "SUBMITTED"), xero_id)

        po.refresh_from_db()
        assert po.status == "fully_received"

    def test_billed_records_xeros_word_without_asserting_delivery(self, supplier: Company) -> None:
        """Being billed is an accounts event; receiving is a Docketworks fact."""
        xero_id = uuid4()
        po = _our_order(
            supplier, created_by=Staff.get_automation_user(), status="submitted", xero_id=xero_id
        )

        transform_purchase_order(_incoming(supplier, po.po_number, "BILLED"), xero_id)

        po.refresh_from_db()
        assert po.xero_status == "BILLED"
        assert po.status == "submitted", "Xero marked goods received that nobody receipted"
        assert not po.po_lines.filter(received_quantity__gt=0).exists()

    def test_a_void_in_xero_is_honoured(self, supplier: Company) -> None:
        """The one Xero status our own order still obeys.

        Xero refuses every write to a voided document, so an order left live
        here would be pushed at forever and fail every time. VOIDED reports the
        fate of Xero's copy rather than asserting anything about the job.
        """
        xero_id = uuid4()
        po = _our_order(
            supplier, created_by=Staff.get_automation_user(), status="submitted", xero_id=xero_id
        )

        transform_purchase_order(_incoming(supplier, po.po_number, "VOIDED"), xero_id)

        po.refresh_from_db()
        assert po.status == "deleted"
        assert po.xero_status == "VOIDED"


class TestXeroRaisedOrders:
    def test_an_order_we_did_not_raise_still_mirrors_in_full(self, supplier: Company) -> None:
        """We do not own it, so Xero remains its record."""
        xero_id = uuid4()
        po = _our_order(supplier, created_by=None, status="draft", xero_id=xero_id)

        transform_purchase_order(_incoming(supplier, po.po_number, "SUBMITTED"), xero_id)

        po.refresh_from_db()
        assert po.status == "submitted"
        line = po.po_lines.get(description="Xero's idea of the line")
        assert line.quantity == Decimal("99")

    def test_billed_no_longer_means_received_even_for_a_xero_order(self, supplier: Company) -> None:
        """Nothing in Xero can establish that material arrived."""
        xero_id = uuid4()
        po = _our_order(supplier, created_by=None, status="draft", xero_id=xero_id)

        transform_purchase_order(_incoming(supplier, po.po_number, "BILLED"), xero_id)

        po.refresh_from_db()
        assert po.status == "submitted"
        assert po.xero_status == "BILLED"
