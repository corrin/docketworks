"""What a purchase order costs in Xero calls, and when it spends them.

Xero holds a copy of the order so the supplier's bill has something to link
against. That fixes the schedule as well as the purpose: bills arrive
overnight, so the only moments Xero needs to hear about are the order leaving
draft, which is the first point a bill can come back, and the receipt that
settles its total. Going back to draft is a third, because Xero has to learn
the order was pulled.

Business risk covered, and it is a bill rather than a bug. Every Xero API call
costs a dollar. An earlier design pushed on every write, and the workspace
saves each field as its own PATCH, so building an eight-line order cost nine
calls at best and thirty-three in a normal session, each one a round trip with
the operator waiting on a vendor. The counting test below is what keeps that
from coming back: it asserts zero, not "few".

That design also could not create an order at all. Xero refuses a purchase
order with no line items, the create page posts a header with no lines, so the
push raised and the create rolled back. Nothing here pushes at creation now,
and the last test states that as a guarantee rather than an accident.
"""

from unittest.mock import patch

import pytest
from django.test import Client

from apps.accounting.types import DocumentResult
from apps.company.models import Company
from apps.job.models import Job
from apps.purchasing.models import PurchaseOrder
from apps.purchasing.tests.factories import make_po_line, make_purchase_order

pytestmark = pytest.mark.django_db

PROVIDER = "apps.purchasing.services.accounting_mirror.get_provider"
PO_LIST_URL = "/api/purchasing/purchase-orders/"


def _detail_url(po: PurchaseOrder) -> str:
    return f"{PO_LIST_URL}{po.id}/"


def _patch(api: Client, po: PurchaseOrder, **fields: object) -> int:
    """Save a change through the real endpoint, under its current ETag."""
    etag = api.get(_detail_url(po)).headers["ETag"]
    return api.patch(
        _detail_url(po),
        data=fields,
        content_type="application/json",
        headers={"If-Match": etag},
    ).status_code


class TestWhatItCosts:
    def test_editing_a_draft_spends_nothing(self, api: Client) -> None:
        """The one that stops this regressing to thirty-three dollars a sitting.

        Zero rather than "not many": any number above it means a field edit is
        reaching a vendor, which is the whole defect.
        """
        po = make_purchase_order(status="draft")
        line = make_po_line(po, quantity="1.00", unit_cost="5.00")

        with patch(PROVIDER) as provider:
            provider.return_value.push_purchase_order.return_value = DocumentResult(success=True)
            assert _patch(api, po, reference="first") == 200
            assert _patch(api, po, reference="second") == 200
            assert _patch(api, po, expected_delivery="2026-10-01") == 200
            assert _patch(api, po, lines=[{"id": str(line.id), "unit_cost": "9.99"}]) == 200

        provider.return_value.push_purchase_order.assert_not_called()

    def test_leaving_draft_spends_one(self, api: Client) -> None:
        po = make_purchase_order(status="draft")
        make_po_line(po, quantity="1.00", unit_cost="5.00")

        with patch(PROVIDER) as provider:
            provider.return_value.push_purchase_order.return_value = DocumentResult(success=True)
            assert _patch(api, po, status="submitted") == 200

        provider.return_value.push_purchase_order.assert_called_once()
        po.refresh_from_db()
        assert po.xero_push_due is False, "a sent order must not stay owing a call"

    def test_going_back_to_draft_spends_one_too(self, api: Client) -> None:
        """Xero has to learn the order was pulled, or its copy outlives ours."""
        po = make_purchase_order(status="submitted")
        make_po_line(po, quantity="1.00", unit_cost="5.00")

        with patch(PROVIDER) as provider:
            provider.return_value.push_purchase_order.return_value = DocumentResult(success=True)
            assert _patch(api, po, status="draft") == 200

        provider.return_value.push_purchase_order.assert_called_once()

    def test_a_status_patch_that_changes_nothing_spends_nothing(self, api: Client) -> None:
        """The negative twin: without it, "every PATCH with a status" passes."""
        po = make_purchase_order(status="submitted")
        make_po_line(po, quantity="1.00", unit_cost="5.00")

        with patch(PROVIDER) as provider:
            provider.return_value.push_purchase_order.return_value = DocumentResult(success=True)
            assert _patch(api, po, status="submitted") == 200

        provider.return_value.push_purchase_order.assert_not_called()

    # The receipt looks the stock-holding job up unconditionally, even for a
    # line allocated to a job, so it has to exist for the path to run at all.
    @pytest.mark.usefixtures("stock_holding_job")
    def test_picking_fully_received_spends_one_not_two(self, api: Client, job: Job) -> None:
        """Both send sites run on this path, and only one may spend.

        Choosing Fully Received in the dropdown is a status transition, and it
        also receipts every line, which is the other thing that sends. A second
        call here would be a dollar for a change the operator made once.
        """
        po = make_purchase_order(status="submitted")
        make_po_line(po, quantity="2.00", unit_cost="5.00", job=job)

        with patch(PROVIDER) as provider:
            provider.return_value.push_purchase_order.return_value = DocumentResult(success=True)
            assert _patch(api, po, status="fully_received") == 200

        provider.return_value.push_purchase_order.assert_called_once()


class TestWhenXeroRefuses:
    def test_a_rejected_order_fails_the_state_change(self, api: Client) -> None:
        """The operator's to fix, so they hear about it while they are looking."""
        po = make_purchase_order(status="draft")
        make_po_line(po, quantity="1.00", unit_cost="5.00")

        with patch(PROVIDER) as provider:
            provider.return_value.push_purchase_order.return_value = DocumentResult(
                success=False, error="Supplier has no contact", status_code=400
            )
            assert _patch(api, po, status="submitted") == 400

        po.refresh_from_db()
        assert po.status == "draft", "the status must not move without Xero taking it"

    def test_an_outage_lets_the_change_stand_and_leaves_the_call_owing(self, api: Client) -> None:
        """A vendor's bad afternoon must not block an operator's own workflow."""
        po = make_purchase_order(status="draft")
        make_po_line(po, quantity="1.00", unit_cost="5.00")

        with patch(PROVIDER) as provider:
            provider.return_value.push_purchase_order.return_value = DocumentResult(
                success=False, error="Rate limit exceeded", status_code=429
            )
            assert _patch(api, po, status="submitted") == 200

        po.refresh_from_db()
        assert po.status == "submitted"
        assert po.xero_push_due is True, "the hourly sync has nothing to find"


def test_an_order_is_created_without_asking_xero(api: Client, supplier: Company) -> None:
    """The create page posts a header with no lines, which Xero would refuse.

    Asserted against the real endpoint and the real payload rather than a
    convenient one: this exact request returned 400 and rolled the create back
    while every test in the suite passed, because the provider was stubbed
    above the validation that refused it.
    """
    with patch(PROVIDER) as provider:
        response = api.post(
            PO_LIST_URL,
            data={"supplier_id": str(supplier.id)},
            content_type="application/json",
        )

    assert response.status_code == 201, response.content
    provider.return_value.push_purchase_order.assert_not_called()
    assert PurchaseOrder.objects.get(id=response.json()["id"]).status == "draft"
