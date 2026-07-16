import uuid
from datetime import date
from decimal import Decimal
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.apps import apps as django_apps
from django.utils import timezone
from rest_framework.test import APIClient

from apps.company.models import Company
from apps.job.models import Job
from apps.testing import BaseTestCase
from apps.workflow.accounting.document_theme_service import (
    resolve_sales_branding_theme,
)
from apps.workflow.accounting.types import (
    DocumentLineItem,
    DocumentTheme,
    InvoicePayload,
    QuotePayload,
)
from apps.workflow.accounting.xero.provider import XeroAccountingProvider
from apps.workflow.models import CompanyDefaults, XeroApp
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
    """Document creation consumes configuration without changing it."""

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

    def test_invoice_creation_stops_when_theme_is_unconfigured(self) -> None:
        """An incomplete Xero setup must fail before any invoice API request."""
        manager = XeroInvoiceManager(
            company=self.company, job=self.job, staff=self.test_staff
        )
        manager.provider = Mock()

        result = manager.create_document(total_amount=Decimal("100"))

        self.assertFalse(result["success"])
        self.assertEqual(result["status"], 400)
        self.assertEqual(result["error_type"], "configuration_error")
        self.assertIn("Configure the Xero sales branding theme", result["error"])
        manager.provider.list_document_themes.assert_not_called()
        manager.provider.create_invoice.assert_not_called()
        self.assertIsNone(CompanyDefaults.get_solo().xero_sales_branding_theme_id)

    def test_quote_creation_stops_when_theme_is_unconfigured(self) -> None:
        """An incomplete Xero setup must fail before any quote API request."""
        manager = XeroQuoteManager(
            company=self.company, job=self.job, staff=self.test_staff
        )
        manager.provider = Mock()

        result = manager.create_document()

        self.assertFalse(result["success"])
        self.assertEqual(result["status"], 400)
        self.assertEqual(result["error_type"], "configuration_error")
        self.assertIn("Configure the Xero sales branding theme", result["error"])
        manager.provider.list_document_themes.assert_not_called()
        manager.provider.create_quote.assert_not_called()
        self.assertIsNone(CompanyDefaults.get_solo().xero_sales_branding_theme_id)

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


class SalesBrandingThemeResolutionTests(BaseTestCase):
    """Migration and setup share one provider-order selection contract."""

    def setUp(self) -> None:
        self.provider = Mock()

    def test_unset_configuration_selects_first_theme(self) -> None:
        """Multiple valid themes must not reintroduce a unique-default requirement."""
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

        selected = resolve_sales_branding_theme(self.provider, None)

        self.assertEqual(selected, first_theme)

    def test_live_custom_selection_is_preserved(self) -> None:
        """Running setup again must not replace an operator's live custom theme."""
        custom_id = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
        custom_theme = DocumentTheme(
            external_id=str(custom_id), name="Terms", is_default=False
        )
        self.provider.list_document_themes.return_value = [
            DocumentTheme(external_id=THEME_ID, name="Standard", is_default=True),
            custom_theme,
        ]

        selected = resolve_sales_branding_theme(self.provider, custom_id)

        self.assertEqual(selected, custom_theme)

    def test_stale_selection_is_replaced_by_first_live_theme(self) -> None:
        """A restored cross-tenant UUID must not leak into new Xero documents."""
        stale_id = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
        first_theme = DocumentTheme(
            external_id=THEME_ID, name="Destination theme", is_default=True
        )
        self.provider.list_document_themes.return_value = [first_theme]

        selected = resolve_sales_branding_theme(self.provider, stale_id)

        self.assertEqual(selected, first_theme)

    def test_empty_theme_list_leaves_configuration_unset(self) -> None:
        """No arbitrary UUID may be invented when the connected tenant has no theme."""
        self.provider.list_document_themes.return_value = []

        selected = resolve_sales_branding_theme(self.provider, None)

        self.assertIsNone(selected)


class SalesBrandingThemeMigrationTests(BaseTestCase):
    """The data migration configures only genuinely connected installations."""

    def setUp(self) -> None:
        self.defaults = CompanyDefaults.get_solo()
        CompanyDefaults.objects.filter(pk=self.defaults.pk).update(
            xero_tenant_id="tenant-123",
            xero_sales_branding_theme_id=None,
            po_prefix="UNCHANGED-",
        )
        CompanyDefaults.clear_cache()
        XeroApp.objects.create(
            label="Migration test",
            client_id="migration-client-id",
            client_secret="migration-client-secret",
            redirect_uri="https://example.test/xero/callback/",
            is_active=True,
            refresh_token="migration-refresh-token",
        )
        self.migration = import_module(
            "apps.workflow.migrations."
            "0011_companydefaults_xero_sales_branding_theme_id"
        )

    @patch("apps.workflow.accounting.registry.get_provider")
    @patch(
        "apps.workflow.accounting.document_theme_service."
        "resolve_sales_branding_theme"
    )
    def test_connected_install_is_backfilled_without_broad_save(
        self,
        mock_resolve_theme: Mock,
        mock_get_provider: Mock,
    ) -> None:
        """Existing deployments must be ready before services restart."""
        selected_theme = DocumentTheme(
            external_id=THEME_ID,
            name="First Xero theme",
            is_default=True,
        )
        mock_resolve_theme.return_value = selected_theme

        self.migration.populate_connected_install_theme(django_apps, Mock())
        self.defaults.refresh_from_db()

        mock_resolve_theme.assert_called_once_with(mock_get_provider.return_value, None)
        self.assertEqual(
            self.defaults.xero_sales_branding_theme_id,
            uuid.UUID(THEME_ID),
        )
        self.assertEqual(self.defaults.po_prefix, "UNCHANGED-")

    @patch(
        "apps.workflow.accounting.document_theme_service."
        "resolve_sales_branding_theme"
    )
    def test_unconnected_install_is_left_for_xero_setup(
        self, mock_resolve_theme: Mock
    ) -> None:
        """Fresh and scrubbed installs have no durable OAuth token at migrate time."""
        XeroApp.objects.filter(is_active=True).update(refresh_token=None)

        self.migration.populate_connected_install_theme(django_apps, Mock())
        self.defaults.refresh_from_db()

        mock_resolve_theme.assert_not_called()
        self.assertIsNone(self.defaults.xero_sales_branding_theme_id)

    @patch(
        "apps.workflow.accounting.document_theme_service."
        "resolve_sales_branding_theme"
    )
    def test_install_without_tenant_is_left_for_xero_setup(
        self, mock_resolve_theme: Mock
    ) -> None:
        """The migration must not contact Xero before onboarding chooses a tenant."""
        CompanyDefaults.objects.filter(pk=self.defaults.pk).update(xero_tenant_id=None)

        self.migration.populate_connected_install_theme(django_apps, Mock())

        mock_resolve_theme.assert_not_called()

    @patch("apps.workflow.accounting.registry.get_provider")
    @patch(
        "apps.workflow.accounting.document_theme_service."
        "resolve_sales_branding_theme"
    )
    def test_connected_install_without_themes_fails_migration(
        self,
        mock_resolve_theme: Mock,
        _mock_get_provider: Mock,
    ) -> None:
        """A connected deployment must not restart with incomplete configuration."""
        mock_resolve_theme.return_value = None

        with self.assertRaisesRegex(RuntimeError, "returned no branding themes"):
            self.migration.populate_connected_install_theme(django_apps, Mock())

        self.assertIsNone(
            CompanyDefaults.objects.values_list(
                "xero_sales_branding_theme_id", flat=True
            ).get(pk=self.defaults.pk)
        )


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
