import uuid
from decimal import Decimal

from django.utils import timezone

from apps.company.models import Company
from apps.job.models import Job
from apps.testing import BaseTestCase
from apps.workflow.accounting.types import DocumentResult
from apps.workflow.views.xero.xero_invoice_manager import XeroInvoiceManager
from apps.workflow.views.xero.xero_quote_manager import XeroQuoteManager


class _FakeProvider:
    def __init__(self, result):
        self.result = result

    def get_account_code(self, account_name="Sales"):
        return "200"

    def create_invoice(self, payload):
        return self.result

    def create_quote(self, payload):
        return self.result

    def add_history_note_to_invoice(self, external_id, note):
        return None

    def add_history_note_to_quote(self, external_id, note):
        return None


class XeroDocumentRawJsonTests(BaseTestCase):
    def setUp(self):
        self.client_obj = Company.objects.create(
            name="Raw JSON Company",
            xero_contact_id=str(uuid.uuid4()),
            xero_last_modified=timezone.now(),
        )
        self.job = Job.objects.create(
            company=self.client_obj,
            name="Raw JSON Job",
            pricing_methodology="fixed_price",
            staff=self.test_staff,
        )

    def test_created_invoice_stores_canonical_raw_json_dict(self):
        raw_response = {
            "_contact": {"_name": "Raw JSON Company"},
            "_invoice_id": str(uuid.uuid4()),
            "_invoice_number": "INV-RAW-1",
            "_sub_total": "100.00",
            "_total_tax": "15.00",
            "_total": "115.00",
            "_amount_due": "115.00",
        }
        provider = _FakeProvider(
            DocumentResult(
                success=True,
                external_id=str(uuid.uuid4()),
                number="INV-RAW-1",
                online_url="https://go.xero.com/invoice",
                raw_response=raw_response,
            )
        )

        manager = XeroInvoiceManager(
            company=self.client_obj,
            job=self.job,
            staff=self.test_staff,
        )
        manager.provider = provider
        manager._attach_workshop_pdf = lambda external_id: None

        result = manager.create_document(total_amount=Decimal("100.00"))

        self.assertTrue(result["success"])
        invoice = self.job.invoices.get()
        self.assertIsInstance(invoice.raw_json, dict)
        self.assertEqual(invoice.raw_json["_contact"]["_name"], "Raw JSON Company")
        self.assertNotIn("full", invoice.raw_json)
        self.assertNotIn("contact", invoice.raw_json)
        self.assertEqual(invoice.total_excl_tax, Decimal("100.00"))
        self.assertEqual(invoice.tax, Decimal("15.00"))
        self.assertEqual(invoice.total_incl_tax, Decimal("115.00"))
        self.assertEqual(invoice.amount_due, Decimal("115.00"))

    def test_created_quote_stores_canonical_raw_json_dict(self):
        self.job.latest_quote.summary = {"cost": 0.0, "rev": 250.0, "hours": 0.0}
        self.job.latest_quote.save(update_fields=["summary"])
        raw_response = {
            "_contact": {"_name": "Raw JSON Company"},
            "_quote_id": str(uuid.uuid4()),
            "_quote_number": "QU-RAW-1",
            "_sub_total": "250.00",
            "_total": "287.50",
        }
        provider = _FakeProvider(
            DocumentResult(
                success=True,
                external_id=str(uuid.uuid4()),
                number="QU-RAW-1",
                online_url="https://go.xero.com/quote",
                raw_response=raw_response,
            )
        )

        manager = XeroQuoteManager(
            company=self.client_obj,
            job=self.job,
            staff=self.test_staff,
        )
        manager.provider = provider

        result = manager.create_document(breakdown=False)

        self.assertTrue(result["success"])
        quote = self.job.quote
        self.assertIsInstance(quote.raw_json, dict)
        self.assertEqual(quote.raw_json["_contact"]["_name"], "Raw JSON Company")
        self.assertNotIn("contact", quote.raw_json)
        self.assertEqual(quote.total_excl_tax, Decimal("250.00"))
        self.assertEqual(quote.total_incl_tax, Decimal("287.50"))
