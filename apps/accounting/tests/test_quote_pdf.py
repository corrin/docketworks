"""Native Xero quote PDF inspection: text matching, failure diagnostics, CLI contract.

Business risk covered: the E2E quote spec's only proof that Xero actually
rendered the configured terms is this inspection — a matcher that misses
Xero's text-layer quirks (line wraps, missing word spaces) would fail a good
quote, and one that reports "terms absent" for a blank render would pass the
blame to the wrong config. The command's single JSON line is a subprocess
contract the spec parses.
"""

import json
import tempfile
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import UUID, uuid4

import pytest
from django.core.management import call_command
from pypdf.errors import PdfReadError
from reportlab.pdfgen import canvas

from apps.accounting.services.quote_pdf import QuotePdfInspection, inspect_quote_pdf
from apps.accounting.types import QuotePdfDocument
from apps.core.models import CompanyDefaults

pytestmark = pytest.mark.django_db

EXPECTED_TERMS = "Terms of trade can be found"
REMOTE_THEME_ID = "11111111-2222-3333-4444-555555555555"


def _write_pdf(text_lines: list[str]) -> Path:
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as temporary:
        pdf_path = Path(temporary.name)
    document = canvas.Canvas(str(pdf_path))
    vertical_position = 800
    for line in text_lines:
        document.drawString(40, vertical_position, line)
        vertical_position -= 20
    document.save()
    return pdf_path


@pytest.fixture(autouse=True)
def _configured_theme() -> None:
    defaults = CompanyDefaults.get_solo()
    CompanyDefaults.objects.filter(pk=defaults.pk).update(
        xero_sales_branding_theme_id=UUID(REMOTE_THEME_ID)
    )
    CompanyDefaults.clear_cache()


def _provider_for_pdf(quote_id: UUID, pdf_path: Path) -> Mock:
    provider = Mock()
    provider.download_quote_pdf.return_value = QuotePdfDocument(
        external_id=str(quote_id),
        document_theme_external_id=REMOTE_THEME_ID,
        temporary_file_path=str(pdf_path),
    )
    return provider


class TestInspectQuotePdf:
    """PDF rendering can regress despite a correct BrandingThemeID payload."""

    @patch("apps.accounting.services.quote_pdf.get_provider")
    def test_terms_marker_survives_pdf_line_wrapping(self, mock_get_provider: Mock) -> None:
        quote_id = uuid4()
        pdf_path = _write_pdf(["Terms of trade", "can be found online"])
        mock_get_provider.return_value = _provider_for_pdf(quote_id, pdf_path)

        result = inspect_quote_pdf(quote_id, EXPECTED_TERMS)

        assert result.contains_expected_text
        assert result.page_count == 1
        assert result.remote_branding_theme_id == REMOTE_THEME_ID
        assert result.configured_branding_theme_id == REMOTE_THEME_ID
        assert not pdf_path.exists()

    @patch("apps.accounting.services.quote_pdf.get_provider")
    def test_missing_or_differently_cased_terms_marker_is_red(
        self, mock_get_provider: Mock
    ) -> None:
        quote_id = uuid4()
        pdf_path = _write_pdf(["TERMS OF TRADE CAN BE FOUND online"])
        mock_get_provider.return_value = _provider_for_pdf(quote_id, pdf_path)

        result = inspect_quote_pdf(quote_id, EXPECTED_TERMS)

        assert not result.contains_expected_text
        assert not pdf_path.exists()

    @patch("apps.accounting.services.quote_pdf.get_provider")
    def test_terms_marker_survives_xero_text_layer_without_word_spaces(
        self, mock_get_provider: Mock
    ) -> None:
        quote_id = uuid4()
        pdf_path = _write_pdf(["Termsoftradecanbefoundonline"])
        mock_get_provider.return_value = _provider_for_pdf(quote_id, pdf_path)

        result = inspect_quote_pdf(quote_id, EXPECTED_TERMS)

        assert result.contains_expected_text
        assert not pdf_path.exists()

    @patch("apps.accounting.services.quote_pdf.get_provider")
    def test_unreadable_pdf_raises_and_keeps_the_download(self, mock_get_provider: Mock) -> None:
        """The read error is what the operator needs, not a tidy temp directory."""
        quote_id = uuid4()
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as temporary:
            temporary.write(b"not a PDF")
            pdf_path = Path(temporary.name)
        mock_get_provider.return_value = _provider_for_pdf(quote_id, pdf_path)

        with pytest.raises(PdfReadError):
            inspect_quote_pdf(quote_id, EXPECTED_TERMS)

        assert pdf_path.exists()
        pdf_path.unlink()

    @patch("apps.accounting.services.quote_pdf.get_provider")
    def test_blank_pages_raise_rather_than_reporting_terms_absent(
        self, mock_get_provider: Mock
    ) -> None:
        """An all-blank PDF is a failed render, not a quote missing its terms."""
        quote_id = uuid4()
        pdf_path = _write_pdf([])
        mock_get_provider.return_value = _provider_for_pdf(quote_id, pdf_path)

        with pytest.raises(ValueError, match="no extractable text"):
            inspect_quote_pdf(quote_id, EXPECTED_TERMS)

        assert pdf_path.exists()
        pdf_path.unlink()

    def test_empty_expected_text_is_rejected_upfront(self) -> None:
        with pytest.raises(ValueError, match="must not be empty"):
            inspect_quote_pdf(uuid4(), "   ")


class TestInspectXeroQuotePdfCommand:
    """The E2E subprocess contract must remain structured and parseable."""

    @patch("apps.accounting.management.commands.inspect_xero_quote_pdf.inspect_quote_pdf")
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

        assert json.loads(output.getvalue()) == {
            "configured_branding_theme_id": REMOTE_THEME_ID,
            "contains_expected_text": False,
            "page_count": 2,
            "quote_id": str(quote_id),
            "remote_branding_theme_id": REMOTE_THEME_ID,
        }
