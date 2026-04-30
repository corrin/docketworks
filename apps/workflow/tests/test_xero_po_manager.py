"""Regression test for PR #222's missed update to XeroPurchaseOrderManager.

PR #222 added a required `staff` argument to `XeroDocumentManager.__init__` and
updated XeroInvoiceManager / XeroQuoteManager and their view call sites, but
missed XeroPurchaseOrderManager and the two view sites that construct it.
Every "Send to Xero" / "Delete from Xero" action on a PO 500'd in production
with `TypeError: __init__() missing 1 required positional argument: 'staff'`.

This test exercises the real constructor through the view (mocking only the
Xero auth check and the manager's `sync_to_xero` method), so it fails if
EITHER:

  * `XeroPurchaseOrderManager.__init__` does not accept `staff`, or
  * the view forgets to pass `staff=request.user`.

Both halves of the bug are caught with a single test.
"""

from unittest.mock import patch

from django.utils import timezone

from apps.client.models import Client
from apps.purchasing.models import PurchaseOrder
from apps.testing import BaseAPITestCase
from apps.workflow.views.xero.xero_po_manager import XeroPurchaseOrderManager


class XeroPurchaseOrderManagerConstructionTests(BaseAPITestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.test_staff.is_office_staff = True
        cls.test_staff.save(update_fields=["is_office_staff"])

        cls.supplier = Client.objects.create(
            name="Test Supplier",
            xero_contact_id="00000000-0000-0000-0000-000000000001",
            xero_last_modified=timezone.now(),
        )
        cls.purchase_order = PurchaseOrder.objects.create(
            supplier=cls.supplier,
            po_number="PO-TEST-0001",
        )

    @patch.object(XeroPurchaseOrderManager, "sync_to_xero")
    @patch("apps.workflow.views.xero.xero_view.ensure_xero_authentication")
    def test_create_view_constructs_manager_without_typeerror(
        self, mock_auth, mock_sync
    ):
        mock_auth.return_value = "tenant-id"
        mock_sync.return_value = {
            "success": True,
            "xero_id": "00000000-0000-0000-0000-000000000abc",
            "online_url": "https://go.xero.com/example",
        }

        self.client.force_authenticate(user=self.test_staff)
        response = self.client.post(
            f"/api/xero/create_purchase_order/{self.purchase_order.id}"
        )

        self.assertNotEqual(
            response.status_code,
            500,
            f"create_xero_purchase_order returned 500. Body: {response.content!r}",
        )
        mock_sync.assert_called_once()
