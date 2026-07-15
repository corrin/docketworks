import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.utils import timezone
from rest_framework.test import APIClient

from apps.company.models import Company
from apps.job.models import Job
from apps.testing import BaseTestCase
from apps.workflow.accounting.types import (
    DocumentLineItem,
    DocumentTheme,
    InvoicePayload,
    QuotePayload,
)
from apps.workflow.accounting.xero.provider import XeroAccountingProvider
from apps.workflow.models import CompanyDefaults
from apps.workflow.views.xero.xero_invoice_manager import XeroInvoiceManager
from apps.workflow.views.xero.xero_quote_manager import XeroQuoteManager
from apps.workflow.views.xero.xero_view import XeroAuthenticationResult

THEME_ID = "11111111-2222-3333-4444-555555555555"


class XeroBrandingThemeProviderTests(BaseTestCase):
    """Xero receives the exact theme selected by the DocketWorks operator."""

    @patch("apps.workflow.accounting.xero.provider.process_xero_data", return_value={})
    @patch.object(XeroAccountingProvider, "_get_api")
    def test_invoice_create_payload_includes_branding_theme_id(
        self, mock_get_api: Mock, _mock_process: Mock
    ) -> None:
        api = Mock()
        api.create_invoices.return_value = (
            SimpleNamespace(
                invoices=[
                    SimpleNamespace(
                        invoice_id=uuid.uuid4(), invoice_number="INV-THEME-1"
                    )
                ]
            ),
            200,
            {},
        )
        mock_get_api.return_value = (api, "tenant-id")

        payload = InvoicePayload(
            client_external_id=str(uuid.uuid4()),
            company_name="Theme Test Company",
            line_items=[
                DocumentLineItem(
                    description="Theme test",
                    quantity=Decimal("1"),
                    unit_amount=Decimal("100"),
                )
            ],
            date=date(2026, 7, 16),
            due_date=date(2026, 7, 16),
            document_theme_external_id=THEME_ID,
        )

        result = XeroAccountingProvider().create_invoice(payload)

        self.assertTrue(result.success)
        sent = api.create_invoices.call_args.kwargs["invoices"]["Invoices"][0]
        self.assertEqual(sent["BrandingThemeID"], THEME_ID)
        self.assertEqual(sent["Contact"]["ContactID"], payload.client_external_id)

    @patch("apps.workflow.accounting.xero.provider.process_xero_data", return_value={})
    @patch.object(XeroAccountingProvider, "_get_api")
    def test_quote_create_payload_includes_branding_theme_without_terms(
        self, mock_get_api: Mock, _mock_process: Mock
    ) -> None:
        api = Mock()
        api.create_quotes.return_value = (
            SimpleNamespace(
                quotes=[
                    SimpleNamespace(quote_id=uuid.uuid4(), quote_number="QU-THEME-1")
                ]
            ),
            200,
            {},
        )
        mock_get_api.return_value = (api, "tenant-id")

        payload = QuotePayload(
            client_external_id=str(uuid.uuid4()),
            company_name="Theme Test Company",
            line_items=[
                DocumentLineItem(
                    description="Theme test",
                    quantity=Decimal("1"),
                    unit_amount=Decimal("100"),
                )
            ],
            date=date(2026, 7, 16),
            expiry_date=date(2026, 8, 15),
            document_theme_external_id=THEME_ID,
        )

        result = XeroAccountingProvider().create_quote(payload)

        self.assertTrue(result.success)
        sent = api.create_quotes.call_args.kwargs["quotes"]["Quotes"][0]
        self.assertEqual(sent["BrandingThemeID"], THEME_ID)
        self.assertNotIn("Terms", sent)

    @patch.object(XeroAccountingProvider, "_get_api")
    def test_list_document_themes_preserves_xero_order_and_default(
        self, mock_get_api: Mock
    ) -> None:
        api = Mock()
        api.get_branding_themes.return_value = SimpleNamespace(
            branding_themes=[
                SimpleNamespace(
                    branding_theme_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                    name="Secondary",
                    sort_order=2,
                ),
                SimpleNamespace(
                    branding_theme_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                    name="Sales Terms",
                    sort_order=0,
                ),
            ]
        )
        mock_get_api.return_value = (api, "tenant-id")

        themes = XeroAccountingProvider().list_document_themes()

        self.assertEqual([theme.name for theme in themes], ["Sales Terms", "Secondary"])
        self.assertTrue(themes[0].is_default)
        self.assertFalse(themes[1].is_default)


class XeroBrandingThemeConfigurationTests(BaseTestCase):
    """No Xero document is created when its required theme is unconfigured."""

    def setUp(self) -> None:
        defaults = CompanyDefaults.get_solo()
        CompanyDefaults.objects.filter(pk=defaults.pk).update(
            xero_sales_branding_theme_id=None
        )
        CompanyDefaults.clear_cache()

        self.company = Company.objects.create(
            name="Missing Theme Company",
            xero_contact_id=str(uuid.uuid4()),
            xero_last_modified=timezone.now(),
        )
        self.job = Job(
            company=self.company,
            name="Missing Theme Job",
            pricing_methodology="fixed_price",
        )
        self.job.save(staff=self.test_staff)

    def test_invoice_creation_stops_before_provider_write(self) -> None:
        manager = XeroInvoiceManager(
            company=self.company, job=self.job, staff=self.test_staff
        )
        manager.provider = Mock()

        result = manager.create_document(total_amount=Decimal("100"))

        self.assertFalse(result["success"])
        self.assertEqual(result["status"], 400)
        self.assertEqual(result["error_type"], "configuration_error")
        self.assertIn("Select a Xero sales branding theme", result["error"])
        manager.provider.create_invoice.assert_not_called()

    def test_quote_creation_stops_before_provider_write(self) -> None:
        manager = XeroQuoteManager(
            company=self.company, job=self.job, staff=self.test_staff
        )
        manager.provider = Mock()

        result = manager.create_document()

        self.assertFalse(result["success"])
        self.assertEqual(result["status"], 400)
        self.assertEqual(result["error_type"], "configuration_error")
        self.assertIn("Select a Xero sales branding theme", result["error"])
        manager.provider.create_quote.assert_not_called()


class XeroBrandingThemeAPITests(BaseTestCase):
    """Office staff can populate the settings selector from live Xero themes."""

    def setUp(self) -> None:
        self.test_staff.is_office_staff = True
        self.test_staff.save(update_fields=["is_office_staff"])
        self.client = APIClient()
        self.client.force_authenticate(user=self.test_staff)

    @patch("apps.workflow.views.xero.xero_view.get_provider")
    @patch("apps.workflow.views.xero.xero_view.ensure_xero_authentication")
    def test_list_branding_themes_returns_selector_contract(
        self, mock_auth: Mock, mock_get_provider: Mock
    ) -> None:
        mock_auth.return_value = XeroAuthenticationResult()
        provider = Mock()
        provider.list_document_themes.return_value = [
            DocumentTheme(external_id=THEME_ID, name="Sales Terms", is_default=True)
        ]
        mock_get_provider.return_value = provider

        response = self.client.get("/api/xero/branding-themes/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            [
                {
                    "branding_theme_id": THEME_ID,
                    "name": "Sales Terms",
                    "is_default": True,
                }
            ],
        )
