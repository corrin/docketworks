"""Purchase-order sync runs one way, and which way depends on who raised it.

Docketworks masters an order it raised, so the inbound sync takes nothing back
for it but the fields Xero itself owns. An order that exists only because Xero
has it has no other source, so Xero keeps its header and lines current.

Business risk covered. The hourly sync used to upsert PO lines straight from
Xero, so a price confirmed when the bill arrived was reverted at the top of the
hour. Separately, Xero's BILLED status set `fully_received` locally, marking
material as received that nobody had receipted — orders with no stock row and
no cost line, which is cost that never reaches a job (KAN-144). That second one
is a semantic fault rather than a direction one: being invoiced is not a claim
that goods arrived, whichever way the data flows.
"""

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from django.utils import timezone

from apps.accounting.types import DocumentResult
from apps.accounts.models import Staff
from apps.company.models import Company
from apps.core.models import CompanyDefaults
from apps.job.models import Job
from apps.job.models.costing import CostLine
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLine, Stock
from apps.purchasing.tests.factories import receive_po_line
from apps.xero.models import XeroError
from apps.xero.tests.conftest import make_po_manager, make_po_provider
from apps.xero.transforms import sync_entities, transform_purchase_order
from apps.xero.validation import XeroValidationError

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


def _sent_order(
    supplier: Company,
    *,
    xero_id: UUID,
    status: str = "submitted",
    dw_raised: bool = False,
) -> PurchaseOrder:
    """An order Xero holds. By default one Xero raised, so Xero is its source.

    The number is what decides, because both systems raise orders and each
    numbers its own. ``created_by`` is left unset either way: it went
    unrecorded for the first eight months, so a fixture that set it would let
    the ownership rule regress to a column that cannot answer the question.
    """
    # "XPO-" stands in for Xero's own numbering: anything outside the
    # instance's prefix. The default prefix IS "PO-", so a fixture reaching for
    # the obvious Xero-looking number would have made every order a local one.
    prefix = CompanyDefaults.get_solo().po_prefix if dw_raised else "XPO-"
    po = PurchaseOrder.objects.create(
        supplier=supplier,
        status=status,
        po_number=f"{prefix}{uuid4().int % 90_000 + 10_000}",
        xero_id=xero_id,
    )
    PurchaseOrderLine.objects.create(
        purchase_order=po,
        xero_line_item_id=uuid4(),
        description="What we ordered",
        quantity=Decimal("4.00"),
        unit_cost=Decimal("12.50"),
    )
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


class TestAnOrderWeRaised:
    """Docketworks masters it, so the sync neither takes nor publishes."""

    def test_xero_cannot_revert_our_line(self, supplier: Company) -> None:
        """The confirmed price survives the hour."""
        xero_id = uuid4()
        po = _sent_order(supplier, xero_id=xero_id, dw_raised=True)

        transform_purchase_order(_incoming(supplier, po.po_number, "SUBMITTED"), xero_id)

        line = po.po_lines.get()
        assert (line.description, line.quantity) == ("What we ordered", Decimal("4.00"))

    def test_xero_cannot_move_our_status(self, supplier: Company) -> None:
        xero_id = uuid4()
        po = _sent_order(supplier, xero_id=xero_id, status="draft", dw_raised=True)

        transform_purchase_order(_incoming(supplier, po.po_number, "SUBMITTED"), xero_id)

        po.refresh_from_db()
        assert po.status == "draft"
        assert po.xero_status == "SUBMITTED", "Xero's own word is still recorded"

    def test_ownership_is_read_from_the_number_not_from_created_by(self, supplier: Company) -> None:
        """created_by went unrecorded until 2026-01-09, so it cannot answer this.

        Measured 2026-09-13 against a production restore: 419 of the 825 orders
        Docketworks raised carry no created_by. Reading ownership from it would
        hand Xero the right to overwrite every one of them on the next pull.
        """
        xero_id = uuid4()
        po = _sent_order(supplier, xero_id=xero_id, dw_raised=True)
        assert po.created_by_id is None, "the fixture must not supply the easy answer"

        transform_purchase_order(_incoming(supplier, po.po_number, "SUBMITTED"), xero_id)

        assert po.po_lines.get().quantity == Decimal("4.00")

    def test_the_sync_never_writes_back_to_xero(self, supplier: Company) -> None:
        """The negative twin: a sync that publishes is the ping-pong loop.

        Absorbing an inbound edit used to be indistinguishable from making a
        local one, so the sync pushed the order back, Xero reported the result
        as a modification, and the two traded it hourly forever on the call
        quota. Nothing in this path may reach the provider at all.
        """
        xero_id = uuid4()
        po = _sent_order(supplier, xero_id=xero_id, dw_raised=True)
        incoming = _incoming(supplier, po.po_number, "SUBMITTED")

        with patch("apps.accounting.registry.get_provider") as provider:
            transform_purchase_order(incoming, xero_id)
            transform_purchase_order(incoming, xero_id)

        provider.assert_not_called()

    def test_absorbing_xeros_own_fields_still_advances_the_etag(self, supplier: Company) -> None:
        """ADR 0003: a row that changed must not keep a client's stale version.

        If an inbound change left ``updated_at`` alone, a client holding the
        pre-sync version would still match on If-Match and overwrite unnoticed.
        """
        xero_id = uuid4()
        po = _sent_order(supplier, xero_id=xero_id, dw_raised=True)
        before = po.updated_at

        transform_purchase_order(_incoming(supplier, po.po_number, "SUBMITTED"), xero_id)

        po.refresh_from_db()
        assert po.updated_at > before, "the row changed but its version did not"


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


class TestReceiptSurvivesXero:
    """GPT: accounting status must not reopen material already received and costed."""

    @pytest.mark.parametrize(
        "receipt", [(Decimal("2"), "partially_received"), (Decimal("4"), "fully_received")]
    )
    @pytest.mark.parametrize("xero_status", ["AUTHORISED", "BILLED", "VOIDED"])
    def test_receipt_survives_a_successful_push_then_pull(
        self,
        supplier: Company,
        job: Job,
        stock_holding_job: Job,
        receipt: tuple[Decimal, str],
        xero_status: str,
    ) -> None:
        quantity, expected_status = receipt
        po = _sent_order(supplier, xero_id=uuid4())
        line = po.po_lines.get()
        po = receive_po_line(line, quantity, job, stock_holding_job, Staff.get_automation_user())
        assert po.status == expected_status
        stocks = Stock.objects.filter(source_purchase_order_line=line)
        costs = CostLine.objects.filter(ext_refs__purchase_order_line_id=str(line.id))
        stock_before = list(stocks.values())
        cost_before = list(costs.values())
        assert stock_before and cost_before
        provider = make_po_provider(DocumentResult(success=True, external_id=str(po.xero_id)))
        assert make_po_manager(po, provider).sync_to_xero()["success"]
        assert provider.update_purchase_order.call_args.args[0].status == "AUTHORISED"
        po.refresh_from_db()
        incoming = _incoming(supplier, po.po_number, xero_status)
        incoming.line_items[0].line_item_id = str(line.xero_line_item_id)
        incoming.line_items[0].quantity = line.quantity
        incoming.line_items[0].description = line.xero_description
        incoming.line_items[0].unit_amount = line.unit_cost

        transform_purchase_order(incoming, str(po.xero_id))

        po.refresh_from_db()
        line.refresh_from_db()
        assert po.status == expected_status
        assert po.xero_status == xero_status
        assert line.received_quantity == Decimal(quantity)
        assert list(stocks.values()) == stock_before
        assert list(costs.values()) == cost_before


@pytest.mark.parametrize("ordered", [Decimal("1"), Decimal("6")])
def test_xero_quantity_amendments_preserve_posted_receipts(
    supplier: Company, job: Job, stock_holding_job: Job, ordered: Decimal
) -> None:
    po = _sent_order(supplier, xero_id=uuid4())
    line = po.po_lines.get()
    receive_po_line(line, Decimal("2"), job, stock_holding_job, Staff.get_automation_user())
    po.refresh_from_db()
    before = PurchaseOrder.objects.values().get(pk=po.pk)
    costs = list(
        CostLine.objects.filter(stockmovement__stock__source_purchase_order_line=line).values()
    )
    stocks = list(Stock.objects.filter(source_purchase_order_line=line).values())
    incoming = _incoming(supplier, po.po_number, "AUTHORISED")
    incoming.line_items[0].line_item_id = str(line.xero_line_item_id)
    incoming.line_items[0].quantity = ordered
    incoming.line_items[0].unit_amount = Decimal("30")
    if ordered < 2:
        with pytest.raises(XeroValidationError, match="net received"):
            transform_purchase_order(incoming, str(po.xero_id))
        incoming.purchase_order_id = str(po.xero_id)
        assert (
            sync_entities([incoming], PurchaseOrder, "purchase_order_id", transform_purchase_order)
            == 0
        )
        assert "net received" in XeroError.objects.get(reference_id=str(po.xero_id)).message
        assert PurchaseOrder.objects.values().get(pk=po.pk) == before
        line.refresh_from_db()
        assert line.quantity == 4
        assert line.unit_cost == Decimal("12.50")
    else:
        transform_purchase_order(incoming, str(po.xero_id))
        po.refresh_from_db()
        line.refresh_from_db()
        assert (line.quantity, line.unit_cost, line.received_quantity) == (
            Decimal("6"),
            Decimal("30"),
            Decimal("2"),
        )
        assert po.status == "partially_received"
    assert (
        list(
            CostLine.objects.filter(stockmovement__stock__source_purchase_order_line=line).values()
        )
        == costs
    )
    assert list(Stock.objects.filter(source_purchase_order_line=line).values()) == stocks
    if ordered >= 2:
        receive_po_line(line, Decimal("2"), job, stock_holding_job, Staff.get_automation_user())
        assert set(
            Stock.objects.filter(source_purchase_order_line=line).values_list(
                "unit_cost", flat=True
            )
        ) == {Decimal("12.50"), Decimal("30")}
