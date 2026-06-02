from decimal import Decimal
from uuid import uuid4

from django.utils import timezone

from apps.accounting.enums import InvoiceStatus
from apps.accounting.models import Invoice, InvoiceLineItem
from apps.client.models import Client
from apps.testing import BaseTestCase


class InvoiceModelTests(BaseTestCase):
    def test_total_amount_sums_reverse_line_items(self):
        client = Client.objects.create(
            name="Invoice Model Client",
            xero_last_modified=timezone.now(),
        )
        invoice = Invoice.objects.create(
            xero_id=uuid4(),
            xero_tenant_id="tenant-id",
            number="INV-001",
            client=client,
            date=timezone.localdate(),
            due_date=timezone.localdate(),
            status=InvoiceStatus.DRAFT,
            total_excl_tax=Decimal("0.00"),
            tax=Decimal("0.00"),
            total_incl_tax=Decimal("0.00"),
            amount_due=Decimal("0.00"),
            xero_last_modified=timezone.now(),
            raw_json={},
        )
        InvoiceLineItem.objects.create(
            invoice=invoice,
            description="Labour",
            line_amount_excl_tax=Decimal("125.50"),
        )
        InvoiceLineItem.objects.create(
            invoice=invoice,
            description="Material",
            line_amount_excl_tax=Decimal("74.50"),
        )

        self.assertEqual(invoice.total_amount, Decimal("200.00"))
