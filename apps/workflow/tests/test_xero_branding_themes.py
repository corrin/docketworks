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
from apps.workflow.accounting.document_theme_service import (
    resolve_and_persist_sales_branding_theme,
)
from apps.workflow.accounting.types import (
    DocumentLineItem,
    DocumentResult,
    DocumentTheme,
    InvoicePayload,
    QuotePayload,
)
from apps.workflow.accounting.xero.provider import XeroAccountingProvider
from apps.workflow.exceptions import AlreadyLoggedException
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
    """An upgraded installation configures its theme before its first write."""

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

    def test_invoice_creation_initialises_first_theme_before_provider_write(
        self,
    ) -> None:
        """A deployment-only upgrade must not require an operator setup command."""
        manager = XeroInvoiceManager(
            company=self.company, job=self.job, staff=self.test_staff
        )
        manager.provider = Mock()
        manager.provider.list_document_themes.return_value = [
            DocumentTheme(
                external_id=THEME_ID,
                name="First Xero theme",
                is_default=False,
            ),
            DocumentTheme(
                external_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                name="Later default-labelled theme",
                is_default=True,
            ),
        ]
        payload = InvoicePayload(
            client_external_id=str(uuid.uuid4()),
            company_name=self.company.name,
            line_items=[],
            date=date(2026, 7, 16),
            due_date=date(2026, 7, 16),
            document_theme_external_id=THEME_ID,
        )
        manager.provider.create_invoice.return_value = DocumentResult(
            success=False,
            error="Stop after observing the outbound payload",
            status_code=400,
        )

        with patch.object(manager, "build_payload", return_value=payload) as build:
            result = manager.create_document(total_amount=Decimal("100"))

        self.assertFalse(result["success"])
        self.assertEqual(result["status"], 400)
        build.assert_called_once_with(
            Decimal("100"), document_theme_external_id=THEME_ID
        )
        manager.provider.create_invoice.assert_called_once_with(payload)
        self.assertEqual(
            CompanyDefaults.get_solo().xero_sales_branding_theme_id,
            uuid.UUID(THEME_ID),
        )

    def test_quote_creation_initialises_first_theme_before_provider_write(self) -> None:
        """Quote creation shares the unattended upgrade path with invoices."""
        manager = XeroQuoteManager(
            company=self.company, job=self.job, staff=self.test_staff
        )
        manager.provider = Mock()
        manager.provider.list_document_themes.return_value = [
            DocumentTheme(
                external_id=THEME_ID,
                name="First Xero theme",
                is_default=True,
            )
        ]
        payload = QuotePayload(
            client_external_id=str(uuid.uuid4()),
            company_name=self.company.name,
            line_items=[],
            date=date(2026, 7, 16),
            expiry_date=date(2026, 8, 15),
            document_theme_external_id=THEME_ID,
        )
        manager.provider.create_quote.return_value = DocumentResult(
            success=False,
            error="Stop after observing the outbound payload",
            status_code=400,
        )

        with patch.object(manager, "build_payload", return_value=payload) as build:
            result = manager.create_document()

        self.assertFalse(result["success"])
        self.assertEqual(result["status"], 400)
        build.assert_called_once_with(
            breakdown=True, document_theme_external_id=THEME_ID
        )
        manager.provider.create_quote.assert_called_once_with(payload)
        self.assertEqual(
            CompanyDefaults.get_solo().xero_sales_branding_theme_id,
            uuid.UUID(THEME_ID),
        )

    def test_invoice_creation_stops_when_xero_has_no_themes(self) -> None:
        """An empty Xero configuration must fail before the invoice write."""
        manager = XeroInvoiceManager(
            company=self.company, job=self.job, staff=self.test_staff
        )
        manager.provider = Mock()
        manager.provider.list_document_themes.return_value = []

        result = manager.create_document()

        self.assertFalse(result["success"])
        self.assertEqual(result["status"], 400)
        self.assertEqual(result["error_type"], "configuration_error")
        self.assertIn("Xero returned no branding themes", result["error"])
        manager.provider.create_invoice.assert_not_called()

    def test_quote_creation_stops_when_xero_has_no_themes(self) -> None:
        """An empty Xero configuration must fail before the quote write."""
        manager = XeroQuoteManager(
            company=self.company, job=self.job, staff=self.test_staff
        )
        manager.provider = Mock()
        manager.provider.list_document_themes.return_value = []

        result = manager.create_document()

        self.assertFalse(result["success"])
        self.assertEqual(result["status"], 400)
        self.assertEqual(result["error_type"], "configuration_error")
        self.assertIn("Xero returned no branding themes", result["error"])
        manager.provider.create_quote.assert_not_called()

    def test_configured_theme_does_not_add_a_xero_read(self) -> None:
        """Normal document creation must not spend quota revalidating stable config."""
        configured_id = uuid.UUID(THEME_ID)
        defaults = CompanyDefaults.get_solo()
        CompanyDefaults.objects.filter(pk=defaults.pk).update(
            xero_sales_branding_theme_id=configured_id
        )
        CompanyDefaults.clear_cache()
        manager = XeroQuoteManager(
            company=self.company, job=self.job, staff=self.test_staff
        )
        manager.provider = Mock()

        selected_id = manager.get_xero_sales_branding_theme_id()

        self.assertEqual(selected_id, THEME_ID)
        manager.provider.list_document_themes.assert_not_called()

    def test_prelogged_theme_lookup_failure_is_not_persisted_twice(self) -> None:
        """The first-use read must preserve the provider's AppError identity."""
        manager = XeroQuoteManager(
            company=self.company, job=self.job, staff=self.test_staff
        )
        manager.provider = Mock()
        prelogged = AlreadyLoggedException(
            RuntimeError("Xero theme lookup failed"), "app-error-123"
        )
        manager.provider.list_document_themes.side_effect = prelogged

        with self.assertRaises(AlreadyLoggedException) as raised:
            manager.create_document()

        self.assertIs(raised.exception, prelogged)
        manager.provider.create_quote.assert_not_called()


class SalesBrandingThemeResolutionTests(BaseTestCase):
    """Setup and first-use initialization share one strict selection contract."""

    def setUp(self) -> None:
        self.defaults = CompanyDefaults.get_solo()
        CompanyDefaults.objects.filter(pk=self.defaults.pk).update(
            xero_sales_branding_theme_id=None,
            po_prefix="UNCHANGED-",
        )
        CompanyDefaults.clear_cache()
        self.defaults = CompanyDefaults.get_solo()
        self.provider = Mock()

    def test_unset_configuration_selects_first_theme_and_is_idempotent(self) -> None:
        """A refactor must not reintroduce default-count checks or broad saves."""
        first_theme = DocumentTheme(
            external_id=THEME_ID,
            name="First by Xero sort order",
            is_default=False,
        )
        self.provider.list_document_themes.return_value = [
            first_theme,
            DocumentTheme(
                external_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                name="Also valid",
                is_default=False,
            ),
        ]

        first_result = resolve_and_persist_sales_branding_theme(
            self.provider, self.defaults
        )
        second_result = resolve_and_persist_sales_branding_theme(
            self.provider, self.defaults
        )
        self.defaults.refresh_from_db()

        self.assertEqual(first_result, first_theme)
        self.assertEqual(second_result, first_theme)
        self.assertEqual(
            self.defaults.xero_sales_branding_theme_id, uuid.UUID(THEME_ID)
        )
        self.assertEqual(self.defaults.po_prefix, "UNCHANGED-")

    def test_live_custom_selection_is_preserved(self) -> None:
        """Running setup again must not replace an operator's live custom theme."""
        custom_id = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
        CompanyDefaults.objects.filter(pk=self.defaults.pk).update(
            xero_sales_branding_theme_id=custom_id
        )
        CompanyDefaults.clear_cache()
        self.defaults = CompanyDefaults.get_solo()
        custom_theme = DocumentTheme(
            external_id=str(custom_id), name="Terms", is_default=False
        )
        self.provider.list_document_themes.return_value = [
            DocumentTheme(external_id=THEME_ID, name="Standard", is_default=True),
            custom_theme,
        ]

        selected = resolve_and_persist_sales_branding_theme(
            self.provider, self.defaults
        )

        self.assertEqual(selected, custom_theme)
        self.assertEqual(
            CompanyDefaults.get_solo().xero_sales_branding_theme_id, custom_id
        )

    def test_stale_selection_is_replaced_by_first_live_theme(self) -> None:
        """A restored cross-tenant UUID must not leak into new Xero documents."""
        CompanyDefaults.objects.filter(pk=self.defaults.pk).update(
            xero_sales_branding_theme_id=uuid.UUID(
                "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
            )
        )
        CompanyDefaults.clear_cache()
        self.defaults = CompanyDefaults.get_solo()
        first_theme = DocumentTheme(
            external_id=THEME_ID, name="Destination theme", is_default=True
        )
        self.provider.list_document_themes.return_value = [first_theme]

        selected = resolve_and_persist_sales_branding_theme(
            self.provider, self.defaults
        )

        self.assertEqual(selected, first_theme)
        self.assertEqual(
            CompanyDefaults.get_solo().xero_sales_branding_theme_id,
            uuid.UUID(THEME_ID),
        )

    def test_empty_theme_list_leaves_configuration_unset(self) -> None:
        """No arbitrary UUID may be invented when the connected tenant has no theme."""
        self.provider.list_document_themes.return_value = []

        selected = resolve_and_persist_sales_branding_theme(
            self.provider, self.defaults
        )

        self.assertIsNone(selected)
        self.assertIsNone(CompanyDefaults.get_solo().xero_sales_branding_theme_id)


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
