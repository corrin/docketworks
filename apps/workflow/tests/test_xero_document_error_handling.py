"""Error contract for Xero document managers.

The managers are service objects, not the HTTP boundary (ADR 0001): an
unexpected exception is persisted once and re-raised unchanged, so the view
can convert it into a 500 carrying ``error_id`` looked up via
``app_error_for``. Only *expected* business outcomes come back as
``success: False`` dicts.
"""

import uuid
from decimal import Decimal
from unittest.mock import Mock, patch

from django.utils import timezone

from apps.company.models import Company
from apps.job.models import Job
from apps.testing import BaseTestCase
from apps.workflow.models import AppError, CompanyDefaults
from apps.workflow.services.error_persistence import app_error_for, persist_app_error
from apps.workflow.views.xero.xero_invoice_manager import XeroInvoiceManager
from apps.workflow.views.xero.xero_quote_manager import XeroQuoteManager

THEME_ID = "11111111-2222-3333-4444-555555555555"


class XeroDocumentManagerErrorContractTests(BaseTestCase):
    """Unexpected provider failures re-raise once; they never become a dict."""

    def setUp(self) -> None:
        defaults = CompanyDefaults.get_solo()
        CompanyDefaults.objects.filter(pk=defaults.pk).update(
            xero_sales_branding_theme_id=uuid.UUID(THEME_ID),
            xero_quote_terms="Client-approved quote terms",
        )
        CompanyDefaults.clear_cache()

        self.company = Company.objects.create(
            name="Error Contract Company",
            xero_contact_id=str(uuid.uuid4()),
            xero_last_modified=timezone.now(),
        )
        self.job = Job(
            company=self.company,
            name="Error Contract Job",
            pricing_methodology="fixed_price",
        )
        self.job.save(staff=self.test_staff)

    def _invoice_manager(self) -> tuple[XeroInvoiceManager, Mock]:
        """Return the manager plus a handle on its mocked provider."""
        manager = XeroInvoiceManager(
            company=self.company, job=self.job, staff=self.test_staff
        )
        provider = Mock()
        manager.provider = provider
        return manager, provider

    def _quote_manager(self) -> tuple[XeroQuoteManager, Mock]:
        manager = XeroQuoteManager(
            company=self.company, job=self.job, staff=self.test_staff
        )
        provider = Mock()
        manager.provider = provider
        return manager, provider

    # --- create -----------------------------------------------------------

    def test_invoice_create_reraises_original(self) -> None:
        """A Xero blow-up must reach the view as the raised error, not a dict."""
        manager, provider = self._invoice_manager()
        provider.create_invoice.side_effect = RuntimeError("Xero exploded")

        with patch.object(XeroInvoiceManager, "build_payload", return_value=Mock()):
            with self.assertRaises(RuntimeError) as caught:
                manager.create_document(total_amount=Decimal("100"))

        self.assertIsNotNone(app_error_for(caught.exception))
        self.assertEqual(str(caught.exception), "Xero exploded")
        self.assertEqual(AppError.objects.count(), 1)

    def test_quote_create_reraises_original(self) -> None:
        manager, provider = self._quote_manager()
        provider.create_quote.side_effect = RuntimeError("Xero exploded")

        with patch.object(XeroQuoteManager, "build_payload", return_value=Mock()):
            with self.assertRaises(RuntimeError) as caught:
                manager.create_document()

        self.assertIsNotNone(app_error_for(caught.exception))
        self.assertEqual(AppError.objects.count(), 1)

    # --- delete -----------------------------------------------------------

    def test_invoice_delete_reraises_original(self) -> None:
        manager, provider = self._invoice_manager()
        provider.delete_invoice.side_effect = RuntimeError("Xero exploded")

        with patch.object(XeroInvoiceManager, "get_xero_id", return_value="xero-1"):
            with self.assertRaises(RuntimeError) as caught:
                manager.delete_document()

        self.assertIsNotNone(app_error_for(caught.exception))
        self.assertEqual(AppError.objects.count(), 1)

    def test_quote_delete_reraises_original(self) -> None:
        manager, provider = self._quote_manager()
        provider.delete_quote.side_effect = RuntimeError("Xero exploded")

        with patch.object(XeroQuoteManager, "get_xero_id", return_value="xero-1"):
            with self.assertRaises(RuntimeError) as caught:
                manager.delete_document()

        self.assertIsNotNone(app_error_for(caught.exception))
        self.assertEqual(AppError.objects.count(), 1)

    # --- dedup regression guard ------------------------------------------

    def test_invoice_delete_does_not_double_persist(self) -> None:
        """The delete path once lacked the pass-through arm and re-persisted."""
        original = RuntimeError("Persisted upstream")
        upstream_error = persist_app_error(original)

        manager, provider = self._invoice_manager()
        provider.delete_invoice.side_effect = original

        with patch.object(XeroInvoiceManager, "get_xero_id", return_value="xero-1"):
            with self.assertRaises(RuntimeError) as caught:
                manager.delete_document()

        self.assertIs(caught.exception, original)
        self.assertEqual(app_error_for(caught.exception), upstream_error)
        self.assertEqual(AppError.objects.count(), 1)

    def test_quote_delete_does_not_double_persist(self) -> None:
        original = RuntimeError("Persisted upstream")
        upstream_error = persist_app_error(original)

        manager, provider = self._quote_manager()
        provider.delete_quote.side_effect = original

        with patch.object(XeroQuoteManager, "get_xero_id", return_value="xero-1"):
            with self.assertRaises(RuntimeError) as caught:
                manager.delete_document()

        self.assertIs(caught.exception, original)
        self.assertEqual(app_error_for(caught.exception), upstream_error)
        self.assertEqual(AppError.objects.count(), 1)

    # --- expected failures still return a dict ----------------------------

    def test_expected_provider_failure_still_returns_dict(self) -> None:
        """A declined Xero call is a business outcome, not an exception."""
        manager, provider = self._invoice_manager()
        provider.create_invoice.return_value = Mock(
            success=False, error="Contact is archived", status_code=400
        )

        with patch.object(XeroInvoiceManager, "build_payload", return_value=Mock()):
            result = manager.create_document(total_amount=Decimal("100"))

        self.assertFalse(result["success"])
        self.assertEqual(result["status"], 400)
        self.assertEqual(AppError.objects.count(), 0)
