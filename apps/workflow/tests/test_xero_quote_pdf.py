"""Tests for native Xero quote PDF inspection."""

from __future__ import annotations

import json
import tempfile
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import UUID, uuid4

from django.core.management import call_command
from django.test import SimpleTestCase
from reportlab.pdfgen import canvas

from apps.testing import BaseTestCase
from apps.workflow.accounting.quote_pdf_service import (
    QuotePdfInspection,
    inspect_quote_pdf,
)
from apps.workflow.accounting.types import QuotePdfDocument
from apps.workflow.accounting.xero.provider import XeroAccountingProvider
from apps.workflow.models import CompanyDefaults

EXPECTED_TERMS = "Terms of trade can be found"
REMOTE_THEME_ID = "11111111-2222-3333-4444-555555555555"


def _write_pdf(text_lines: list[str]) -> Path:
    temporary = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    temporary.close()
    pdf_path = Path(temporary.name)
    document = canvas.Canvas(str(pdf_path))
    vertical_position = 800
    for line in text_lines:
        document.drawString(40, vertical_position, line)
        vertical_position -= 20
    document.save()
    return pdf_path


class XeroQuotePdfProviderTests(SimpleTestCase):
    """The provider must use Xero's rendered PDF, not recreate a local document."""

    @patch.object(XeroAccountingProvider, "_get_api")
    def test_download_quote_pdf_returns_xero_file_and_theme(
        self, mock_get_api: Mock
    ) -> None:
        quote_id = str(uuid4())
        pdf_path = _write_pdf([EXPECTED_TERMS])
        api = Mock()
        api.get_quote.return_value = SimpleNamespace(
            quotes=[
                SimpleNamespace(
                    quote_id=quote_id,
                    branding_theme_id=REMOTE_THEME_ID,
                )
            ]
        )
        api.get_quote_as_pdf.return_value = str(pdf_path)
        mock_get_api.return_value = (api, "tenant-id")

        result = XeroAccountingProvider().download_quote_pdf(quote_id)

        self.assertEqual(result.external_id, quote_id)
        self.assertEqual(result.document_theme_external_id, REMOTE_THEME_ID)
        self.assertEqual(result.temporary_file_path, pdf_path)
        api.get_quote.assert_called_once_with("tenant-id", quote_id)
        api.get_quote_as_pdf.assert_called_once_with("tenant-id", quote_id)
        pdf_path.unlink()


class QuotePdfInspectionTests(BaseTestCase):
    """PDF rendering can regress despite a correct BrandingThemeID payload."""

    def setUp(self) -> None:
        defaults = CompanyDefaults.get_solo()
        CompanyDefaults.objects.filter(pk=defaults.pk).update(
            xero_sales_branding_theme_id=UUID(REMOTE_THEME_ID)
        )
        CompanyDefaults.clear_cache()

    def _provider_for_pdf(self, quote_id: UUID, pdf_path: Path) -> Mock:
        provider = Mock()
        provider.download_quote_pdf.return_value = QuotePdfDocument(
            external_id=str(quote_id),
            document_theme_external_id=REMOTE_THEME_ID,
            temporary_file_path=pdf_path,
        )
        return provider

    @patch("apps.workflow.accounting.quote_pdf_service.get_provider")
    def test_terms_marker_survives_pdf_line_wrapping(
        self, mock_get_provider: Mock
    ) -> None:
        quote_id = uuid4()
        pdf_path = _write_pdf(["Terms of trade", "can be found online"])
        mock_get_provider.return_value = self._provider_for_pdf(quote_id, pdf_path)

        result = inspect_quote_pdf(quote_id, EXPECTED_TERMS)

        self.assertTrue(result.contains_expected_text)
        self.assertEqual(result.page_count, 1)
        self.assertEqual(result.remote_branding_theme_id, REMOTE_THEME_ID)
        self.assertEqual(result.configured_branding_theme_id, REMOTE_THEME_ID)
        self.assertFalse(pdf_path.exists())

    @patch("apps.workflow.accounting.quote_pdf_service.get_provider")
    def test_missing_or_differently_cased_terms_marker_is_red(
        self, mock_get_provider: Mock
    ) -> None:
        quote_id = uuid4()
        pdf_path = _write_pdf(["TERMS OF TRADE CAN BE FOUND online"])
        mock_get_provider.return_value = self._provider_for_pdf(quote_id, pdf_path)

        result = inspect_quote_pdf(quote_id, EXPECTED_TERMS)

        self.assertFalse(result.contains_expected_text)
        self.assertFalse(pdf_path.exists())

    @patch("apps.workflow.accounting.quote_pdf_service.get_provider")
    def test_terms_marker_survives_xero_text_layer_without_word_spaces(
        self, mock_get_provider: Mock
    ) -> None:
        quote_id = uuid4()
        pdf_path = _write_pdf(["Termsoftradecanbefoundonline"])
        mock_get_provider.return_value = self._provider_for_pdf(quote_id, pdf_path)

        result = inspect_quote_pdf(quote_id, EXPECTED_TERMS)

        self.assertTrue(result.contains_expected_text)
        self.assertFalse(pdf_path.exists())

    @patch("apps.workflow.accounting.quote_pdf_service.get_provider")
    def test_unreadable_pdf_still_removes_download(
        self, mock_get_provider: Mock
    ) -> None:
        quote_id = uuid4()
        temporary = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        temporary.write(b"not a PDF")
        temporary.close()
        pdf_path = Path(temporary.name)
        mock_get_provider.return_value = self._provider_for_pdf(quote_id, pdf_path)

        with self.assertRaises(Exception):
            inspect_quote_pdf(quote_id, EXPECTED_TERMS)

        self.assertFalse(pdf_path.exists())


class InspectXeroQuotePdfCommandTests(SimpleTestCase):
    """The E2E subprocess contract must remain structured and parseable."""

    @patch("apps.workflow.management.commands.inspect_xero_quote_pdf.inspect_quote_pdf")
    def test_command_emits_one_json_result(self, mock_inspect: Mock) -> None:
        quote_id = uuid4()
        mock_inspect.return_value = QuotePdfInspection(
            quote_id=str(quote_id),
            remote_branding_theme_id=REMOTE_THEME_ID,
            configured_branding_theme_id=REMOTE_THEME_ID,
            page_count=2,
            contains_expected_text=False,
        )
        output = StringIO()

        call_command(
            "inspect_xero_quote_pdf",
            str(quote_id),
            expected_text=EXPECTED_TERMS,
            stdout=output,
        )

        self.assertEqual(
            json.loads(output.getvalue()),
            {
                "configured_branding_theme_id": REMOTE_THEME_ID,
                "contains_expected_text": False,
                "page_count": 2,
                "quote_id": str(quote_id),
                "remote_branding_theme_id": REMOTE_THEME_ID,
            },
        )
