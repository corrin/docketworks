"""
Tests for workshop PDF service, particularly HTML to ReportLab conversion.

Test cases are based on real job notes from the database to ensure the
conversion handles actual Quill editor output correctly.
"""

import os
from decimal import Decimal
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase
from django.utils import timezone
from PIL import Image
from PyPDF2 import PdfReader

from apps.client.models import Client
from apps.job.models import Job
from apps.job.models.costing import CostLine
from apps.job.services.workshop_pdf_service import (
    convert_html_to_reportlab,
    create_delivery_docket_pdf,
    format_hours_display,
)
from apps.testing import BaseTestCase
from apps.workflow.models import CompanyDefaults


class FormatHoursDisplayTests(SimpleTestCase):
    """Tests for the format_hours_display function."""

    def test_whole_hours(self):
        self.assertEqual(format_hours_display(2.0), "2h")

    def test_hours_and_minutes(self):
        self.assertEqual(format_hours_display(2.5), "2h 30m")

    def test_minutes_only(self):
        self.assertEqual(format_hours_display(0.25), "15m")

    def test_zero(self):
        self.assertEqual(format_hours_display(0.0), "0h")

    def test_none(self):
        self.assertEqual(format_hours_display(None), "0h")

    def test_large_value(self):
        self.assertEqual(format_hours_display(10.75), "10h 45m")

    def test_rounding(self):
        # 1.33 hours = 79.8 minutes, rounds to 80 = 1h 20m
        self.assertEqual(format_hours_display(1.33), "1h 20m")

    def test_integer_input(self):
        self.assertEqual(format_hours_display(3), "3h")


class ConvertHtmlToReportlabTests(SimpleTestCase):
    """Tests for the convert_html_to_reportlab function."""

    # -------------------------------------------------------------------------
    # Basic paragraph handling - the core fix for preserving newlines
    # -------------------------------------------------------------------------

    def test_simple_paragraphs_preserve_line_breaks(self):
        """Each <p> tag should create a line break in the output."""
        html = "<p>Line 1</p><p>Line 2</p><p>Line 3</p>"
        result = convert_html_to_reportlab(html)
        self.assertEqual(result, "Line 1<br/>Line 2<br/>Line 3")

    def test_blank_line_creates_paragraph_spacing(self):
        """Quill's blank line (<p><br></p>) should create double line break."""
        html = "<p>Section 1</p><p><br></p><p>Section 2</p>"
        result = convert_html_to_reportlab(html)
        self.assertEqual(result, "Section 1<br/><br/>Section 2")

    def test_multiple_blank_lines_collapse_to_two(self):
        """Multiple consecutive blank lines should collapse to max 2 breaks."""
        html = "<p>Section 1</p><p><br></p><p><br></p><p><br></p><p>Section 2</p>"
        result = convert_html_to_reportlab(html)
        self.assertEqual(result, "Section 1<br/><br/>Section 2")

    def test_trailing_blank_lines_stripped(self):
        """Trailing blank lines should be removed."""
        html = "<p>Content</p><p><br></p><p><br></p>"
        result = convert_html_to_reportlab(html)
        self.assertEqual(result, "Content")

    # -------------------------------------------------------------------------
    # Real job notes from database - Job 96577 (RACK AND TABLE)
    # -------------------------------------------------------------------------

    def test_real_job_96577_rack_and_table(self):
        """
        Real job notes with bold headers and blank line section separator.
        Should preserve structure with line breaks between items.
        """
        html = (
            "<p><strong>RACK</strong></p>"
            "<p>REPLACE 1 X CHANNEL</p>"
            "<p>STRAIGHTEN RACK IN GENERAL</p>"
            "<p><br></p>"
            "<p><strong>TABLE</strong></p>"
            "<p>WELD 3 X HOLES IN TABLE TOP</p>"
            "<p>POLISH TOP FACE (ROTARY BRUSH FINISH)</p>"
            "<p><br></p><p><br></p>"
        )
        result = convert_html_to_reportlab(html)

        # Should have bold tags preserved
        self.assertIn("<b>RACK</b>", result)
        self.assertIn("<b>TABLE</b>", result)

        # Should have line breaks between items
        self.assertIn("REPLACE 1 X CHANNEL<br/>STRAIGHTEN RACK", result)

        # Should have paragraph break (double <br/>) between sections
        self.assertIn("RACK IN GENERAL<br/><br/><b>TABLE</b>", result)

        # Should NOT have trailing breaks
        self.assertFalse(result.endswith("<br/>"))

    # -------------------------------------------------------------------------
    # Real job notes - Job 96573 (Kitchen wall structural)
    # -------------------------------------------------------------------------

    def test_real_job_96573_structural_with_inline_bold(self):
        """
        Real job with inline bold text within a paragraph.
        Tests that partial bold formatting is preserved correctly.
        """
        html = (
            "<p>JOB TO BE BROKEN DOWN INTO SEGMENTS WITH SPECIFIC OVERALL "
            "SIZES TO BE CONFIRMED<strong> (SIZES USED ARE FOR QUOTING "
            "PURPOSES ONLY)</strong></p>"
        )
        result = convert_html_to_reportlab(html)

        # Inline bold should be preserved (note: "ARE" is in the original text)
        self.assertIn("<b> (SIZES USED ARE FOR QUOTING PURPOSES ONLY)</b>", result)

    # -------------------------------------------------------------------------
    # Real job notes - Job 96567 (with underline)
    # -------------------------------------------------------------------------

    def test_real_job_96567_with_underline(self):
        """
        Real job with underlined section headers.
        Tests that <u> tags are preserved.
        """
        html = (
            "<p><u>MATERIALS</u></p>"
            "<p>30x30x1.5mm S/Steel SHS - 1@ 1mtr long </p>"
            "<p><br></p>"
            "<p>Grind Cut &amp; Dropsaw - 0.75 hr</p>"
            "<p>Prep &amp; Weld - 0.75 hr\t</p>"
            "<p><br></p>"
        )
        result = convert_html_to_reportlab(html)

        # Underline should be preserved
        self.assertIn("<u>MATERIALS</u>", result)

        # HTML entities should be decoded/preserved
        self.assertIn("&amp;", result)  # ReportLab handles this

        # Line breaks separate content (blank line creates paragraph break)
        self.assertIn("1mtr long", result)
        self.assertIn("<br/><br/>Grind Cut", result)  # Blank line becomes double break

    # -------------------------------------------------------------------------
    # Real job notes - Job 96576 (with styled spans)
    # -------------------------------------------------------------------------

    def test_real_job_96576_strips_style_attributes(self):
        """
        Real job with Quill's inline style spans.
        Style attributes should be stripped, content preserved.
        """
        html = (
            '<p><strong style="background-color: rgb(255, 255, 255); '
            'color: rgb(34, 34, 34);">MATERIALS</strong></p>'
            '<p><span style="background-color: rgb(255, 255, 255); '
            'color: rgb(34, 34, 34);">4mm Ali Sheet 5052 - 1@ 3000x1500</span></p>'
        )
        result = convert_html_to_reportlab(html)

        # Bold should be converted, style stripped
        self.assertIn("<b>MATERIALS</b>", result)

        # Span content should be preserved, span tag removed
        self.assertIn("4mm Ali Sheet 5052", result)
        self.assertNotIn("<span", result)
        self.assertNotIn("background-color", result)

    # -------------------------------------------------------------------------
    # Edge cases
    # -------------------------------------------------------------------------

    def test_empty_string_returns_na(self):
        """Empty string should return N/A."""
        self.assertEqual(convert_html_to_reportlab(""), "N/A")

    def test_none_returns_na(self):
        """None should return N/A."""
        self.assertEqual(convert_html_to_reportlab(None), "N/A")

    def test_plain_text_without_tags(self):
        """Plain text without HTML tags should pass through unchanged."""
        text = "Plain text without any HTML"
        result = convert_html_to_reportlab(text)
        self.assertEqual(result, text)

    def test_whitespace_only_returns_na(self):
        """Whitespace-only content should return N/A."""
        self.assertEqual(convert_html_to_reportlab("   \n\t  "), "N/A")

    # -------------------------------------------------------------------------
    # Formatting tag conversions
    # -------------------------------------------------------------------------

    def test_strong_converts_to_b(self):
        """<strong> should convert to <b>."""
        html = "<p><strong>Bold text</strong></p>"
        result = convert_html_to_reportlab(html)
        self.assertIn("<b>Bold text</b>", result)
        self.assertNotIn("<strong>", result)

    def test_em_converts_to_i(self):
        """<em> should convert to <i>."""
        html = "<p><em>Italic text</em></p>"
        result = convert_html_to_reportlab(html)
        self.assertIn("<i>Italic text</i>", result)
        self.assertNotIn("<em>", result)

    def test_s_converts_to_strike(self):
        """<s> (strikethrough) should convert to <strike>."""
        html = "<p><s>Struck text</s></p>"
        result = convert_html_to_reportlab(html)
        self.assertIn("<strike>Struck text</strike>", result)
        self.assertNotIn("<s>", result)

    def test_anchor_converts_to_link(self):
        """<a href="..."> should convert to <link href="...">."""
        html = '<p><a href="https://example.com">Click here</a></p>'
        result = convert_html_to_reportlab(html)
        self.assertIn('<link href="https://example.com">Click here</link>', result)
        self.assertNotIn("<a ", result)

    # -------------------------------------------------------------------------
    # List handling
    # -------------------------------------------------------------------------

    def test_ordered_list_converts_to_numbered(self):
        """<ol> should convert to numbered list with line breaks."""
        html = "<ol><li>First</li><li>Second</li><li>Third</li></ol>"
        result = convert_html_to_reportlab(html)
        self.assertIn("1. First", result)
        self.assertIn("2. Second", result)
        self.assertIn("3. Third", result)

    def test_unordered_list_converts_to_bullets(self):
        """<ul> should convert to bullet list with line breaks."""
        html = "<ul><li>Apple</li><li>Banana</li></ul>"
        result = convert_html_to_reportlab(html)
        self.assertIn("• Apple", result)
        self.assertIn("• Banana", result)

    # -------------------------------------------------------------------------
    # Heading handling
    # -------------------------------------------------------------------------

    def test_h1_converts_to_font_size_bold(self):
        """<h1> should convert to large bold text."""
        html = "<h1>Main Heading</h1>"
        result = convert_html_to_reportlab(html)
        self.assertIn('<font size="18"><b>Main Heading</b></font>', result)

    def test_h2_converts_to_font_size_bold(self):
        """<h2> should convert to bold text with appropriate size."""
        html = "<h2>Sub Heading</h2>"
        result = convert_html_to_reportlab(html)
        self.assertIn('<font size="16"><b>Sub Heading</b></font>', result)

    # -------------------------------------------------------------------------
    # Special elements
    # -------------------------------------------------------------------------

    def test_blockquote_converts_to_italic(self):
        """<blockquote> should convert to italic."""
        html = "<blockquote>Quoted text</blockquote>"
        result = convert_html_to_reportlab(html)
        self.assertIn("<i>Quoted text</i>", result)

    def test_pre_converts_to_courier_font(self):
        """<pre> should convert to Courier font."""
        html = "<pre>Code block</pre>"
        result = convert_html_to_reportlab(html)
        self.assertIn('<font face="Courier">Code block</font>', result)

    def test_br_tags_preserved(self):
        """<br> tags should be preserved as <br/>."""
        html = "<p>Line one<br>Line two</p>"
        result = convert_html_to_reportlab(html)
        self.assertIn("Line one<br/>Line two", result)

    # -------------------------------------------------------------------------
    # Quill UI element removal
    # -------------------------------------------------------------------------

    def test_quill_ui_spans_removed(self):
        """Quill UI elements (class='ql-ui') should be completely removed."""
        html = '<p>Text<span class="ql-ui">UI element</span>More text</p>'
        result = convert_html_to_reportlab(html)
        self.assertNotIn("UI element", result)
        self.assertNotIn("ql-ui", result)
        self.assertIn("TextMore text", result)


def _create_test_image(width=500, height=100):
    """Create a minimal PNG image for testing."""
    img = Image.new("RGB", (width, height), color="navy")
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


class DeliveryDocketPDFTests(BaseTestCase):
    """Tests for delivery docket PDF generation."""

    def setUp(self):
        # Upload a test logo_wide to CompanyDefaults
        company = CompanyDefaults.get_solo()
        img_buf = _create_test_image()
        company.logo_wide.save(
            "test_logo_wide.png",
            SimpleUploadedFile(
                "test_logo_wide.png", img_buf.read(), content_type="image/png"
            ),
            save=True,
        )
        self._logo_path = company.logo_wide.path

        self.client_obj = Client.objects.create(
            name="Test Client",
            xero_last_modified=timezone.now(),
        )
        self.job = Job.objects.create(
            client=self.client_obj,
            name="Test Delivery Job",
            description="Deliver some steel",
        )
        # create_delivery_docket_pdf doesn't need workshop hours,
        # but add a minimal estimate so the job is well-formed
        estimate = self.job.cost_sets.filter(kind="estimate").first()
        if estimate:
            CostLine.objects.create(
                cost_set=estimate,
                kind="time",
                desc="Fabrication",
                quantity=Decimal("2.000"),
                unit_cost=Decimal("32.00"),
                unit_rev=Decimal("105.00"),
                accounting_date=timezone.now().date(),
            )

    def tearDown(self):
        # Clean up the uploaded test image
        if os.path.exists(self._logo_path):
            os.remove(self._logo_path)

    def test_delivery_docket_is_exactly_two_pages(self):
        """Delivery docket should be exactly 2 pages: company copy + customer copy."""
        pdf_buffer = create_delivery_docket_pdf(self.job)
        reader = PdfReader(pdf_buffer)
        self.assertEqual(
            len(reader.pages),
            2,
            f"Expected 2 pages (company + customer copy), got {len(reader.pages)}",
        )
