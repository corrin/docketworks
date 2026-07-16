"""Tests for XeroReadOnlyProvider — suppressed writes, live-read passthrough.

Every test patches ``XeroAccountingProvider._get_api`` to raise, proving the
read-only stubs never touch the real Xero API. ``persist_app_error`` must not
fire either: a suppressed write is not an error, so no AppError rows appear.
"""

import uuid
from decimal import Decimal
from typing import Any
from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone

from apps.company.models import Company
from apps.job.models import Job
from apps.testing import BaseTestCase
from apps.workflow.accounting.registry import get_provider
from apps.workflow.accounting.types import DocumentLineItem, POPayload
from apps.workflow.accounting.xero.provider import XeroAccountingProvider
from apps.workflow.accounting.xero.readonly_provider import XeroReadOnlyProvider
from apps.workflow.models import AppError, CompanyDefaults, XeroAccount, XeroApp
from apps.workflow.views.xero.xero_invoice_manager import XeroInvoiceManager
from apps.workflow.views.xero.xero_quote_manager import XeroQuoteManager

_API_FORBIDDEN = AssertionError(
    "XERO_READONLY provider must not touch the Xero API for writes"
)


def _no_api() -> Any:
    raise _API_FORBIDDEN


class XeroReadOnlyRegistryTests(BaseTestCase):
    @override_settings(XERO_READONLY=True)
    def test_flag_routes_xero_backend_to_readonly_provider(self) -> None:
        self.assertIsInstance(get_provider(), XeroReadOnlyProvider)

    @override_settings(XERO_READONLY=False)
    def test_without_flag_real_provider_is_returned(self) -> None:
        provider = get_provider()
        self.assertIsInstance(provider, XeroAccountingProvider)
        self.assertNotIsInstance(provider, XeroReadOnlyProvider)


class XeroPingReadonlyFieldTests(BaseTestCase):
    """The E2E pre-flight reads xero_readonly off /api/xero/ping/."""

    def _ping_data(self) -> dict[str, bool]:
        from rest_framework.test import APIRequestFactory, force_authenticate

        from apps.workflow.views.xero.xero_view import xero_ping

        request = APIRequestFactory().get("/api/xero/ping/")
        force_authenticate(request, user=self.test_staff)
        response = xero_ping(request)
        self.assertEqual(response.status_code, 200)
        data: dict[str, bool] = response.data
        return data

    @override_settings(XERO_READONLY=True)
    def test_ping_reports_readonly_true(self) -> None:
        self.assertIs(self._ping_data()["xero_readonly"], True)

    @override_settings(XERO_READONLY=False)
    def test_ping_reports_readonly_false(self) -> None:
        self.assertIs(self._ping_data()["xero_readonly"], False)

    @override_settings(
        PRODUCTION_XERO_CLIENT_IDS=["prod-client"],
        XERO_READONLY=False,
    )
    def test_ping_reports_production_xero_client_true(self) -> None:
        XeroApp.objects.create(
            label="Production",
            client_id="prod-client",
            client_secret="secret",
            redirect_uri="https://example.test/callback",
            is_active=True,
        )

        self.assertIs(self._ping_data()["xero_production_client"], True)

    @override_settings(
        PRODUCTION_XERO_CLIENT_IDS=["prod-client"],
        XERO_READONLY=False,
    )
    def test_ping_reports_production_xero_client_false(self) -> None:
        XeroApp.objects.create(
            label="Development",
            client_id="dev-client",
            client_secret="secret",
            redirect_uri="https://example.test/callback",
            is_active=True,
        )

        self.assertIs(self._ping_data()["xero_production_client"], False)


@override_settings(XERO_READONLY=True)
class XeroReadOnlyProviderTests(BaseTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.company = Company.objects.create(
            name="[TEST] Readonly Company", xero_last_modified=timezone.now()
        )
        self.job = Job.objects.create(
            company=self.company,
            name="[TEST] Readonly Job",
            pricing_methodology="fixed_price",
            staff=self.test_staff,
        )
        XeroAccount.objects.create(
            xero_id=uuid.uuid4(),
            account_name="Sales",
            account_code="200",
            xero_last_modified=timezone.now(),
            raw_json={},
        )
        # Sales documents require a configured branding theme before any
        # provider call; without it create_document stops at the config guard.
        defaults = CompanyDefaults.get_solo()
        CompanyDefaults.objects.filter(pk=defaults.pk).update(
            xero_sales_branding_theme_id=uuid.uuid4()
        )
        CompanyDefaults.clear_cache()
        self.addCleanup(CompanyDefaults.clear_cache)

        self._api_patcher = patch.object(
            XeroAccountingProvider, "_get_api", side_effect=_API_FORBIDDEN
        )
        self._api_patcher.start()
        self.addCleanup(self._api_patcher.stop)
        self.provider = XeroReadOnlyProvider()

    def _assert_no_app_errors(self) -> None:
        self.assertEqual(AppError.objects.count(), 0)

    # --- Contacts ---

    def test_create_contact_persists_fake_id_and_succeeds(self) -> None:
        result = self.provider.create_contact(self.company)

        self.assertTrue(result.success)
        self.company.refresh_from_db()
        self.assertEqual(result.external_id, self.company.xero_contact_id)
        # Must be a well-formed UUID: the frontend Xero badge keys off it
        uuid.UUID(self.company.xero_contact_id)
        self.assertEqual(result.name, self.company.name)
        self._assert_no_app_errors()

    def test_update_contact_succeeds_without_api(self) -> None:
        self.company.xero_contact_id = str(uuid.uuid4())
        self.company.save(update_fields=["xero_contact_id"])

        result = self.provider.update_contact(self.company)

        self.assertTrue(result.success)
        self.assertEqual(result.external_id, self.company.xero_contact_id)
        self._assert_no_app_errors()

    def test_update_contact_without_id_upserts_like_real_provider(self) -> None:
        """sync_company_to_xero creates the contact when no ID exists; the
        readonly provider must mirror that upsert, never succeed with a
        missing external_id."""
        self.assertIsNone(self.company.xero_contact_id)

        result = self.provider.update_contact(self.company)

        self.assertTrue(result.success)
        self.assertIsNotNone(result.external_id)
        self.company.refresh_from_db()
        self.assertEqual(result.external_id, self.company.xero_contact_id)
        self._assert_no_app_errors()

    # --- Documents through the real managers ---

    def test_create_invoice_stub_drives_invoice_manager(self) -> None:
        self.company.xero_contact_id = str(uuid.uuid4())
        self.company.save(update_fields=["xero_contact_id"])

        manager = XeroInvoiceManager(
            company=self.company, job=self.job, staff=self.test_staff
        )
        manager.provider = self.provider
        # PDF generation is not under test (see test_xero_document_raw_json.py)
        with patch.object(manager, "_attach_workshop_pdf", return_value=None):
            result = manager.create_document(total_amount=Decimal("100.00"))

        self.assertTrue(result["success"])
        invoice = self.job.invoices.get()
        self.assertTrue(invoice.number.startswith("INV-E2E-"))
        self.assertTrue(
            invoice.online_url.startswith("https://go.xero.com/app/invoicing/edit/")
        )
        self.assertIs(invoice.raw_json["_e2e_stub"], True)
        self.assertEqual(invoice.total_excl_tax, Decimal("100.00"))
        self.assertEqual(invoice.tax, Decimal("15.00"))
        self.assertEqual(invoice.total_incl_tax, Decimal("115.00"))
        self.assertEqual(invoice.amount_due, Decimal("115.00"))
        self._assert_no_app_errors()

    def test_create_quote_stub_drives_quote_manager(self) -> None:
        self.company.xero_contact_id = str(uuid.uuid4())
        self.company.save(update_fields=["xero_contact_id"])
        self.job.latest_quote.summary = {"cost": 0.0, "rev": 250.0, "hours": 0.0}
        self.job.latest_quote.save(update_fields=["summary"])

        manager = XeroQuoteManager(
            company=self.company, job=self.job, staff=self.test_staff
        )
        manager.provider = self.provider

        result = manager.create_document(breakdown=False)

        self.assertTrue(result["success"])
        quote = self.job.quote
        self.assertTrue(quote.number.startswith("QU-E2E-"))
        self.assertTrue(
            quote.online_url.startswith("https://go.xero.com/app/quotes/edit/")
        )
        self.assertIs(quote.raw_json["_e2e_stub"], True)
        self.assertEqual(quote.total_excl_tax, Decimal("250.00"))
        self.assertEqual(quote.total_incl_tax, Decimal("287.50"))
        self._assert_no_app_errors()

    # --- Document deletes (no pre-read of the fake ID) ---

    def test_delete_document_stubs_succeed_without_api(self) -> None:
        for delete in (
            self.provider.delete_invoice,
            self.provider.delete_quote,
            self.provider.delete_purchase_order,
        ):
            external_id = str(uuid.uuid4())
            result = delete(external_id)
            self.assertTrue(result.success)
            self.assertEqual(result.external_id, external_id)
        self._assert_no_app_errors()

    # --- Purchase orders ---

    def _po_payload(self, external_id: str | None = None) -> POPayload:
        return POPayload(
            supplier_external_id=str(uuid.uuid4()),
            supplier_name="[TEST] Supplier",
            po_number="PO-0042",
            line_items=[
                DocumentLineItem(
                    description="Widget",
                    quantity=Decimal("2"),
                    unit_amount=Decimal("10.00"),
                )
            ],
            date=timezone.localdate(),
            external_id=external_id,
        )

    def test_create_purchase_order_stub(self) -> None:
        result = self.provider.create_purchase_order(self._po_payload())

        self.assertTrue(result.success)
        assert result.external_id is not None
        uuid.UUID(result.external_id)
        self.assertEqual(result.number, "PO-0042")
        assert result.raw_response is not None
        self.assertEqual(result.raw_response["line_items"], [])
        self.assertIs(result.raw_response["_e2e_stub"], True)
        self._assert_no_app_errors()

    def test_update_purchase_order_keeps_external_id(self) -> None:
        external_id = str(uuid.uuid4())
        result = self.provider.update_purchase_order(self._po_payload(external_id))

        self.assertTrue(result.success)
        self.assertEqual(result.external_id, external_id)
        self._assert_no_app_errors()

    def test_update_purchase_order_without_external_id_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.provider.update_purchase_order(self._po_payload())

    # --- Attachments and history notes ---

    def test_attachment_and_history_note_stubs_return_true(self) -> None:
        external_id = str(uuid.uuid4())
        self.assertIs(
            self.provider.attach_file_to_invoice(external_id, "job.pdf", b"pdf"), True
        )
        self.assertIs(
            self.provider.add_history_note_to_invoice(external_id, "note"), True
        )
        self.assertIs(
            self.provider.add_history_note_to_quote(external_id, "note"), True
        )
        self._assert_no_app_errors()

    # --- Sync ---

    def test_run_full_sync_skips_and_never_syncs(self) -> None:
        with patch(
            "apps.workflow.api.xero.sync.synchronise_xero_data",
            side_effect=_API_FORBIDDEN,
        ):
            events = list(self.provider.run_full_sync())

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["severity"], "warning")
        self.assertIn("XERO_READONLY", events[0]["message"])
        self._assert_no_app_errors()
