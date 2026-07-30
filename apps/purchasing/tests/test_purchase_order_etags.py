"""Purchase-order mutations must enforce full-precision optimistic concurrency."""

from datetime import timedelta

from django.utils import timezone

from apps.purchasing.etag import generate_po_etag
from apps.purchasing.models import PurchaseOrder
from apps.testing import BaseAPITestCase
from apps.workflow.models import AppError


class PurchaseOrderETagTests(BaseAPITestCase):
    def setUp(self) -> None:
        super().setUp()
        self.client.force_authenticate(self.test_staff)
        self.purchase_order = PurchaseOrder.objects.create(
            po_number="PO-ETAG-1",
            created_by=self.test_staff,
        )
        self.detail_url = f"/api/purchasing/purchase-orders/{self.purchase_order.id}/"

    def _current_etag(self) -> str:
        response = self.client.get(self.detail_url)
        self.assertEqual(response.status_code, 200)
        return response["ETag"]

    def test_patch_requires_if_match(self) -> None:
        response = self.client.patch(self.detail_url, {}, format="json")

        self.assertEqual(response.status_code, 428)

    def test_patch_rejects_a_stale_etag(self) -> None:
        stale_etag = self._current_etag()
        PurchaseOrder.objects.filter(pk=self.purchase_order.pk).update(
            reference="Concurrent edit",
            updated_at=timezone.now(),
        )

        response = self.client.patch(
            self.detail_url,
            {"reference": "Overwriting edit"},
            format="json",
            HTTP_IF_MATCH=stale_etag,
        )

        self.assertEqual(response.status_code, 412)
        self.assertIn("error_id", response.json()["details"])
        self.purchase_order.refresh_from_db()
        self.assertEqual(self.purchase_order.reference, "Concurrent edit")

    def test_delivery_receipt_requires_if_match(self) -> None:
        response = self.client.post(
            "/api/purchasing/delivery-receipts/",
            {
                "purchase_order_id": str(self.purchase_order.id),
                "allocations": {},
            },
            format="json",
        )

        self.assertEqual(response.status_code, 428)

    def test_delivery_receipt_rejects_a_stale_etag(self) -> None:
        stale_etag = self._current_etag()
        PurchaseOrder.objects.filter(pk=self.purchase_order.pk).update(
            reference="Concurrent receipt edit",
            updated_at=timezone.now(),
        )

        response = self.client.post(
            "/api/purchasing/delivery-receipts/",
            {
                "purchase_order_id": str(self.purchase_order.id),
                "allocations": {},
            },
            format="json",
            HTTP_IF_MATCH=stale_etag,
        )

        self.assertEqual(response.status_code, 412)
        self.assertIn("error_id", response.json()["details"])
        self.assertEqual(AppError.objects.count(), 1)

    def test_patch_rejects_a_weak_if_match_tag(self) -> None:
        current_etag = self._current_etag()

        response = self.client.patch(
            self.detail_url,
            {"reference": "Weak edit"},
            format="json",
            HTTP_IF_MATCH=f"W/{current_etag}",
        )

        self.assertEqual(response.status_code, 412)
        self.purchase_order.refresh_from_db()
        self.assertIsNone(self.purchase_order.reference)

    def test_etag_distinguishes_changes_within_one_millisecond(self) -> None:
        first_timestamp = self.purchase_order.updated_at
        self.purchase_order.updated_at = first_timestamp + timedelta(microseconds=100)

        later_etag = generate_po_etag(self.purchase_order)
        self.purchase_order.updated_at = first_timestamp

        self.assertNotEqual(generate_po_etag(self.purchase_order), later_etag)
