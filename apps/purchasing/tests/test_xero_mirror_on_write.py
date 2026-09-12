"""The accounting system's copy is written when ours is, or neither is.

Xero holds the order so the supplier's bill has something to reconcile
against. Docketworks masters the order and Xero mirrors it, so the mirror is
written inside the same transaction as the local change: a refusal rolls our
change back rather than leaving an order here that no bill can be matched to.

Business risk covered. Nothing pushed at all in v1: the only path to Xero was
two endpoints with no caller, so an order reached the supplier and never
reached Xero, and the control on paying for things nobody ordered had nothing
to match against. The design that replaced it committed locally and queued the
push, which made a send that never happened invisible — the operator saw the
order save, and only a bill arriving with nothing to match said otherwise. It
then needed an hourly sweep to find what the queue had lost, and that sweep was
a second scheduled Xero driver whose staleness test matched every order raised
before the column it read existed.
"""

from unittest.mock import patch

import pytest
from django.test import Client

from apps.accounting.types import DocumentResult
from apps.accounts.models import Staff
from apps.company.models import Company
from apps.purchasing.models import PurchaseOrder
from apps.purchasing.tests.factories import make_po_line, make_purchase_order

pytestmark = pytest.mark.django_db

PROVIDER = "apps.purchasing.services.purchase_order_service.get_provider"


def _patch_order(api: Client, po: PurchaseOrder, reference: str) -> int:
    """Save a header change through the real endpoint, under its ETag."""
    etag = api.get(f"/api/purchasing/purchase-orders/{po.id}/").headers["ETag"]
    return api.patch(
        f"/api/purchasing/purchase-orders/{po.id}/",
        data={"reference": reference},
        content_type="application/json",
        headers={"If-Match": etag},
    ).status_code


class TestAChangeSavedHere:
    def test_reaches_the_accounting_system(self, api: Client) -> None:
        """No queue between the save and the mirror: one is the other."""
        po = make_purchase_order(status="submitted", created_by=Staff.get_automation_user())
        make_po_line(po, quantity="1.00", unit_cost="5.00")

        with patch(PROVIDER) as provider:
            provider.return_value.push_purchase_order.return_value = DocumentResult(success=True)
            assert _patch_order(api, po, "confirmed") == 200

        provider.return_value.push_purchase_order.assert_called_once()
        assert provider.return_value.push_purchase_order.call_args.args[0].id == po.id

    def test_is_rolled_back_when_the_accounting_system_refuses_it(self, api: Client) -> None:
        """The negative twin: without it, a mirror that never ran still passes."""
        po = make_purchase_order(status="submitted", created_by=Staff.get_automation_user())
        make_po_line(po, quantity="1.00", unit_cost="5.00")

        with patch(PROVIDER) as provider:
            provider.return_value.push_purchase_order.return_value = DocumentResult(
                success=False, error="Supplier has no contact", status_code=400
            )
            assert _patch_order(api, po, "confirmed") == 400

        po.refresh_from_db()
        assert po.reference != "confirmed", "the local write must not outlive the refusal"

    def test_tells_a_vendor_outage_apart_from_a_bad_order(self, api: Client) -> None:
        """A quota or an outage says the same write succeeds later; 400 says never."""
        po = make_purchase_order(status="submitted", created_by=Staff.get_automation_user())
        make_po_line(po, quantity="1.00", unit_cost="5.00")

        with patch(PROVIDER) as provider:
            provider.return_value.push_purchase_order.return_value = DocumentResult(
                success=False, error="Rate limit exceeded", status_code=429
            )
            assert _patch_order(api, po, "confirmed") == 503


class TestAnOrderRaisedHere:
    def _create(self, api: Client, supplier_id: str) -> int:
        return api.post(
            "/api/purchasing/purchase-orders/",
            data={
                "supplier_id": supplier_id,
                "reference": "new order",
                "lines": [{"description": "Steel", "quantity": 2, "unit_cost": "10.00"}],
            },
            content_type="application/json",
        ).status_code

    def test_is_created_in_the_accounting_system_immediately(
        self, api: Client, supplier: Company
    ) -> None:
        """Immediately, like an invoice — not once some later sweep notices."""

        with patch(PROVIDER) as provider:
            provider.return_value.push_purchase_order.return_value = DocumentResult(success=True)
            assert self._create(api, str(supplier.id)) == 201

        provider.return_value.push_purchase_order.assert_called_once()

    def test_does_not_exist_here_when_the_accounting_system_refuses_it(
        self, api: Client, supplier: Company
    ) -> None:
        """An order Xero never took is the bug this whole path exists to prevent."""
        before = PurchaseOrder.objects.count()

        with patch(PROVIDER) as provider:
            provider.return_value.push_purchase_order.return_value = DocumentResult(
                success=False, error="Supplier has no contact", status_code=400
            )
            assert self._create(api, str(supplier.id)) == 400

        assert PurchaseOrder.objects.count() == before
