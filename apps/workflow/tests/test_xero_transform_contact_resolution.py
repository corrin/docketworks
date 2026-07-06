from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone as django_timezone

from apps.company.models import Company
from apps.workflow.api.xero.transforms import (
    _extract_required_fields_xero,
    resolve_company_from_xero_contact,
    transform_purchase_order,
    transform_quote,
)


def _make_contact(contact_id: str, **extra):
    return SimpleNamespace(contact_id=contact_id, **extra)


class XeroTransformContactResolutionTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(
            name="Existing Company",
            xero_contact_id="contact-123",
            xero_last_modified=django_timezone.now(),
        )

    @patch("apps.workflow.api.xero.transforms.get_or_fetch_company")
    def test_resolve_client_uses_embedded_contact_without_follow_up_get(
        self, mock_get_or_fetch
    ):
        contact = _make_contact("contact-123", name="Existing Company")

        resolved = resolve_company_from_xero_contact(contact, "INV-001")

        self.assertEqual(resolved.id, self.company.id)
        mock_get_or_fetch.assert_not_called()

    @patch("apps.workflow.api.xero.transforms.get_or_fetch_company")
    def test_resolve_client_falls_back_only_when_embedded_contact_missing(
        self, mock_get_or_fetch
    ):
        mock_get_or_fetch.return_value = self.company

        resolved = resolve_company_from_xero_contact(
            SimpleNamespace(contact_id="contact-123"), "INV-001"
        )

        self.assertEqual(resolved.id, self.company.id)
        mock_get_or_fetch.assert_called_once_with("contact-123", "INV-001")

    @patch("apps.workflow.api.xero.transforms.resolve_company_from_xero_contact")
    def test_invoice_extract_uses_contact_resolver(self, mock_resolve_client):
        mock_resolve_client.return_value = self.company
        invoice = SimpleNamespace(
            contact=_make_contact("contact-123", name="Existing Company"),
            invoice_number="INV-001",
            date="2026-05-05",
            sub_total=100,
            total_tax=15,
            total=115,
            amount_due=115,
            updated_date_utc=datetime(2026, 5, 5, tzinfo=timezone.utc),
        )

        fields = _extract_required_fields_xero("invoice", invoice, "inv-xero-id")

        self.assertEqual(fields["company"].id, self.company.id)
        mock_resolve_client.assert_called_once_with(invoice.contact, "INV-001")

    @patch("apps.workflow.api.xero.transforms.resolve_company_from_xero_contact")
    @patch("apps.workflow.api.xero.transforms.process_xero_data")
    @patch("apps.workflow.api.xero.transforms.Quote.objects.get_or_create")
    def test_quote_transform_uses_contact_resolver(
        self, mock_get_or_create, mock_process_xero_data, mock_resolve_client
    ):
        mock_resolve_client.return_value = self.company
        mock_process_xero_data.return_value = {
            "_status": {"_value_": "DRAFT"},
            "_date": "2026-05-05",
            "_sub_total": 100,
            "_total": 115,
            "_updated_date_utc": "2026-05-05T00:00:00+00:00",
        }
        mock_quote = SimpleNamespace(number="Q-001")
        mock_get_or_create.return_value = (mock_quote, True)
        quote = SimpleNamespace(
            contact=_make_contact("contact-123", name="Existing Company"),
            quote_number="Q-001",
        )

        transform_quote(quote, "quote-xero-id")

        mock_resolve_client.assert_called_once_with(
            quote.contact, "quote quote-xero-id"
        )

    @patch("apps.workflow.api.xero.transforms.resolve_company_from_xero_contact")
    @patch("apps.workflow.api.xero.transforms.process_xero_data")
    @patch("apps.workflow.api.xero.transforms.PurchaseOrder.objects.filter")
    @patch("apps.workflow.api.xero.transforms.PurchaseOrder.objects.create")
    def test_purchase_order_transform_uses_contact_resolver(
        self,
        mock_create,
        mock_filter,
        mock_process_xero_data,
        mock_resolve_client,
    ):
        mock_resolve_client.return_value = self.company
        mock_process_xero_data.return_value = {"_line_items": []}
        mock_filter.return_value.first.return_value = None
        mock_po = SimpleNamespace(
            po_number="PO-001",
            lines=SimpleNamespace(all=lambda: []),
            save=lambda *args, **kwargs: None,
        )
        mock_create.return_value = mock_po
        xero_po = SimpleNamespace(
            contact=_make_contact("contact-123", name="Existing Company"),
            purchase_order_number="PO-001",
            date="2026-05-05",
            status="DRAFT",
            updated_date_utc=datetime(2026, 5, 5, tzinfo=timezone.utc),
            line_items=[],
        )

        transform_purchase_order(xero_po, "po-xero-id")

        mock_resolve_client.assert_called_once_with(xero_po.contact, "PO-001")
