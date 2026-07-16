from django.utils import timezone

from apps.company.models import Company
from apps.job.models import Job
from apps.purchasing.models import PurchaseOrder
from apps.purchasing.serializers import (
    JobForPurchasingSerializer,
    PurchaseOrderDetailSerializer,
)
from apps.testing import BaseTestCase
from apps.workflow.models import XeroPayItem


class JobForPurchasingSerializerTests(BaseTestCase):
    def test_client_name_uses_related_client_name(self):
        company = Company.objects.create(
            name="Serializer Company",
            xero_last_modified=timezone.now(),
        )
        job = Job.objects.create(
            name="Serializer Job",
            company=company,
            created_by=self.test_staff,
            default_xero_pay_item=XeroPayItem.get_ordinary_time(),
            staff=self.test_staff,
        )

        data = JobForPurchasingSerializer(job).data

        self.assertEqual(data["company_name"], "Serializer Company")


class PurchaseOrderDetailSerializerTests(BaseTestCase):
    def test_related_display_fields_use_related_objects(self):
        supplier = Company.objects.create(
            name="Serializer Supplier",
            xero_contact_id="00000000-0000-0000-0000-000000000001",
            xero_last_modified=timezone.now(),
        )
        purchase_order = PurchaseOrder.objects.create(
            supplier=supplier,
            created_by=self.test_staff,
            po_number="PO-SERIALIZER-001",
            order_date=timezone.localdate(),
        )
        purchase_order.detail_lines = []

        data = PurchaseOrderDetailSerializer(purchase_order).data

        self.assertEqual(data["supplier"], "Serializer Supplier")
        self.assertEqual(data["supplier_id"], str(supplier.id))
        self.assertEqual(
            data["created_by_name"], self.test_staff.get_display_full_name()
        )
        self.assertTrue(data["supplier_has_xero_id"])

    def test_missing_related_display_fields_keep_api_defaults(self):
        purchase_order = PurchaseOrder.objects.create(
            po_number="PO-SERIALIZER-002",
            order_date=timezone.localdate(),
        )
        purchase_order.detail_lines = []

        data = PurchaseOrderDetailSerializer(purchase_order).data

        self.assertEqual(data["supplier"], "")
        self.assertIsNone(data["supplier_id"])
        self.assertEqual(data["created_by_name"], "")
        self.assertFalse(data["supplier_has_xero_id"])
