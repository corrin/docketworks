"""
Tests for workshop PDF service, particularly HTML to ReportLab conversion.

Test cases are based on real job notes from the database to ensure the
conversion handles actual Quill editor output correctly.
"""

from decimal import Decimal
from typing import Any

from django.db import connection
from django.test import SimpleTestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from pypdf import PdfReader

from apps.company.models import Company, ContactMethod, Person
from apps.job.models import CostSet, Job, LabourSubtype
from apps.job.models.costing import CostLine
from apps.job.services.workshop_pdf_service import (
    _primary_phone_for_job,
    convert_html_to_reportlab,
    create_delivery_docket_pdf,
    create_workshop_pdf,
    format_hours_display,
    get_job_for_delivery_docket_pdf,
    get_job_for_workshop_pdf,
    get_time_breakdown,
    get_workshop_hours,
)
from apps.testing import BaseTestCase


class PrimaryPhoneForJobTests(BaseTestCase):
    """Phone preference order on workshop PDFs and delivery dockets:
    the job contact's number first, then the company's own number."""

    def setUp(self) -> None:
        self.client_obj = Company.objects.create(
            name="Phone Pref Company",
            xero_last_modified=timezone.now(),
        )
        self.person = Person.objects.create(name="Jane Doe")
        self.job = Job.objects.create(
            company=self.client_obj,
            person=self.person,
            name="Phone Pref Job",
            staff=self.test_staff,
        )
        ContactMethod.objects.create(
            company=self.client_obj,
            method_type=ContactMethod.MethodType.PHONE,
            value="09 555 0001",
        )

    def test_contact_phone_wins_when_contact_has_one(self) -> None:
        ContactMethod.objects.create(
            person=self.person,
            method_type=ContactMethod.MethodType.PHONE,
            value="021 555 100",
        )
        loaded_job = get_job_for_delivery_docket_pdf(self.job.id)

        self.assertEqual(_primary_phone_for_job(loaded_job), "021 555 100")

    def test_falls_back_to_client_phone_when_contact_has_none(self) -> None:
        loaded_job = get_job_for_delivery_docket_pdf(self.job.id)

        self.assertEqual(_primary_phone_for_job(loaded_job), "09 555 0001")

    def test_no_contact_uses_client_phone(self) -> None:
        self.job.person = None
        self.job.save(staff=self.test_staff, update_fields=["person"])
        loaded_job = get_job_for_delivery_docket_pdf(self.job.id)

        self.assertEqual(_primary_phone_for_job(loaded_job), "09 555 0001")

    def test_plain_job_phone_lookup_is_rejected(self) -> None:
        with self.assertRaisesMessage(
            ValueError, "PDF phone fields must be loaded before rendering"
        ):
            _primary_phone_for_job(self.job)

    def test_annotated_contact_phone_wins_when_contact_has_one(self) -> None:
        ContactMethod.objects.create(
            person=self.person,
            method_type=ContactMethod.MethodType.PHONE,
            value="021 555 100",
        )

        loaded_job = get_job_for_workshop_pdf(self.job.id)

        self.assertEqual(_primary_phone_for_job(loaded_job), "021 555 100")

    def test_annotated_job_falls_back_to_client_phone(self) -> None:
        loaded_job = get_job_for_workshop_pdf(self.job.id)

        self.assertEqual(_primary_phone_for_job(loaded_job), "09 555 0001")


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


class WorkshopHourBreakdownTests(BaseTestCase):
    """Tests for subtype-based workshop PDF hour calculations."""

    def setUp(self) -> None:
        self.client_obj = Company.objects.create(
            name="PDF Time Company",
            xero_last_modified=timezone.now(),
        )
        self.job = Job.objects.create(
            company=self.client_obj,
            name="PDF Time Job",
            staff=self.test_staff,
        )

    def _add_time(
        self,
        cost_set: CostSet,
        subtype_name: str,
        hours: str,
        desc: str,
    ) -> CostLine:
        kwargs: dict[str, Any] = {}
        today = timezone.localdate()
        if cost_set.kind == "actual":
            from apps.workflow.models import XeroPayItem

            kwargs = {
                "staff": self.test_staff,
                "xero_pay_item": XeroPayItem.objects.get(name="Ordinary Time"),
                "meta": {
                    "staff_id": str(self.test_staff.id),
                    "date": today.isoformat(),
                    "is_billable": True,
                    "wage_rate_multiplier": 1.0,
                },
            }

        return CostLine.objects.create(
            cost_set=cost_set,
            kind="time",
            labour_subtype=LabourSubtype.objects.get(name=subtype_name),
            desc=desc,
            quantity=Decimal(str(hours)),
            unit_cost=Decimal("40.00"),
            unit_rev=Decimal("105.00"),
            accounting_date=today,
            **kwargs,
        )

    def _page_texts(self) -> list[str]:
        pdf_buffer = create_workshop_pdf(self.job)
        reader = PdfReader(pdf_buffer)
        return [page.extract_text() or "" for page in reader.pages]

    def test_budget_breakdown_skips_office_labour_and_buckets_production(
        self,
    ) -> None:
        estimate = self.job.latest_estimate
        self._add_time(estimate, "Workshop", "4.000", "Workshop")
        self._add_time(estimate, "Onsite", "5.000", "Onsite")
        self._add_time(estimate, "Supervision", "2.000", "Supervision")
        self._add_time(estimate, "Admin", "3.000", "Admin")
        self._add_time(estimate, "Quoting", "1.000", "Quoting")

        self.assertEqual(get_workshop_hours(self.job), 11.0)

        breakdown = get_time_breakdown(self.job)
        self.assertEqual(breakdown["budgeted_hours"], 11.0)
        subtype_hours = {
            row["name"]: row["estimated_hours"]
            for row in breakdown["subtype_breakdown"]
        }
        self.assertEqual(
            subtype_hours,
            {
                "WORKSHOP TIME": 4.0,
                "Onsite Time": 5.0,
                "Supervision Time": 2.0,
            },
        )
        workshop_rows = [
            row for row in breakdown["subtype_breakdown"] if row["is_workshop"]
        ]
        self.assertEqual([row["name"] for row in workshop_rows], ["WORKSHOP TIME"])

    def test_actual_hours_skip_office_like_subtypes_for_pdf(self) -> None:
        estimate = self.job.latest_estimate
        self._add_time(estimate, "Workshop", "8.000", "Workshop")
        self._add_time(estimate, "Admin", "2.000", "Admin")

        actual = self.job.latest_actual
        self._add_time(actual, "Workshop", "3.000", "Workshop actual")
        self._add_time(actual, "Admin", "2.000", "Admin actual")

        breakdown = get_time_breakdown(self.job)

        self.assertEqual(breakdown["used_hours"], 3.0)
        self.assertEqual(breakdown["remaining_hours"], 5.0)
        self.assertEqual(breakdown["production_budgeted_hours"], 8.0)
        self.assertEqual(breakdown["production_used_hours"], 3.0)
        self.assertEqual(breakdown["production_remaining_hours"], 5.0)
        self.assertEqual(
            breakdown["staff_breakdown"],
            [{"name": "Test Staff", "hours": 3.0}],
        )

    def test_missing_time_line_subtype_raises_instead_of_hiding_hours(self) -> None:
        """A migration or direct SQL edit can leave a time line without subtype.

        The workshop PDF must fail visibly so the data is repaired, not silently
        exclude those hours from remaining-work calculations.
        """
        estimate = self.job.latest_estimate
        line = self._add_time(estimate, "Workshop", "4.000", "Workshop")
        CostLine.objects.filter(id=line.id).update(labour_subtype=None)

        with self.assertRaisesRegex(ValueError, "has no labour subtype"):
            get_workshop_hours(self.job)

    def test_materials_used_shows_retail_line_total_when_known(self) -> None:
        estimate = self.job.latest_estimate
        assert estimate is not None
        self._add_time(estimate, "Workshop", "2.000", "Workshop")

        actual = self.job.latest_actual
        assert actual is not None
        CostLine.objects.create(
            cost_set=actual,
            kind="material",
            desc="Known retail material",
            quantity=Decimal("2.500"),
            unit_cost=Decimal("5.00"),
            unit_rev=Decimal("12.00"),
            accounting_date=timezone.localdate(),
        )
        CostLine.objects.create(
            cost_set=actual,
            kind="material",
            desc="Unknown retail material",
            quantity=Decimal("2.000"),
            unit_cost=Decimal("99.00"),
            unit_rev=Decimal("0.00"),
            accounting_date=timezone.localdate(),
        )

        pdf_buffer = create_workshop_pdf(self.job)
        reader = PdfReader(pdf_buffer)
        text = "\n".join(page.extract_text() or "" for page in reader.pages)

        self.assertIn("RETAIL PRICE", text)
        self.assertIn("Known retail material", text)
        self.assertIn("$30.00", text)
        self.assertIn("Unknown retail material", text)
        self.assertNotIn("$0.00", text)
        self.assertNotIn("$198.00", text)

    def test_preloaded_workshop_pdf_render_does_not_query_cost_lines(self) -> None:
        """Workshop PDF rendering must use the loaded CostLine and phone data."""
        estimate = self.job.latest_estimate
        assert estimate is not None
        self._add_time(estimate, "Workshop", "4.000", "Workshop")
        ContactMethod.objects.create(
            company=self.job.company,
            method_type=ContactMethod.MethodType.PHONE,
            value="09 555 0001",
        )

        actual = self.job.latest_actual
        assert actual is not None
        self._add_time(actual, "Workshop", "1.500", "Workshop actual")
        CostLine.objects.create(
            cost_set=actual,
            kind="material",
            desc="Preloaded material",
            quantity=Decimal("2.000"),
            unit_cost=Decimal("5.00"),
            unit_rev=Decimal("12.00"),
            accounting_date=timezone.localdate(),
        )

        loaded_job = get_job_for_workshop_pdf(self.job.id)

        with CaptureQueriesContext(connection) as captured:
            pdf_buffer = create_workshop_pdf(loaded_job)

        cost_line_queries = [
            query["sql"] for query in captured if 'FROM "job_costline"' in query["sql"]
        ]
        contact_method_queries = [
            query["sql"]
            for query in captured
            if 'FROM "company_clientcontactmethod"' in query["sql"]
        ]
        self.assertEqual(cost_line_queries, [])
        self.assertEqual(contact_method_queries, [])
        self.assertGreater(len(pdf_buffer.getvalue()), 0)

    def test_time_used_starts_on_page_two_when_specs_fit_page_one(self) -> None:
        estimate = self.job.latest_estimate
        assert estimate is not None
        self._add_time(estimate, "Workshop", "2.000", "Workshop")
        self.job.description = "Short description marker"
        self.job.notes = "<p>Short notes marker</p>"
        self.job.save(staff=self.test_staff, update_fields=["description", "notes"])

        page_texts = self._page_texts()

        self.assertIn("Short description marker", page_texts[0])
        self.assertIn("Short notes marker", page_texts[0])
        self.assertNotIn("Time Used", page_texts[0])
        self.assertIn("Time Used", page_texts[1])

    def test_long_description_finishes_before_notes_and_time_used(self) -> None:
        estimate = self.job.latest_estimate
        assert estimate is not None
        self._add_time(estimate, "Workshop", "2.000", "Workshop")
        self.job.description = "Long description marker " + (
            "fabrication detail " * 900
        )
        self.job.notes = "<p>Short notes after long description marker</p>"
        self.job.save(staff=self.test_staff, update_fields=["description", "notes"])

        page_texts = self._page_texts()
        combined_text = "\n".join(page_texts)

        self.assertLess(
            combined_text.index("Long description marker"),
            combined_text.index("Short notes after long description marker"),
        )
        self.assertLess(
            combined_text.index("Short notes after long description marker"),
            combined_text.index("Time Used"),
        )
        self.assertGreater(
            next(i for i, text in enumerate(page_texts) if "Time Used" in text),
            1,
        )

    def test_long_notes_finish_before_time_used(self) -> None:
        estimate = self.job.latest_estimate
        assert estimate is not None
        self._add_time(estimate, "Workshop", "2.000", "Workshop")
        self.job.description = "Short description before long notes marker"
        self.job.notes = "<p>Long notes marker " + ("instruction step " * 900) + "</p>"
        self.job.save(staff=self.test_staff, update_fields=["description", "notes"])

        page_texts = self._page_texts()
        combined_text = "\n".join(page_texts)

        self.assertLess(
            combined_text.index("Short description before long notes marker"),
            combined_text.index("Long notes marker"),
        )
        self.assertLess(
            combined_text.index("Long notes marker"),
            combined_text.index("Time Used"),
        )
        self.assertGreater(
            next(i for i, text in enumerate(page_texts) if "Time Used" in text),
            1,
        )


class DeliveryDocketPDFTests(BaseTestCase):
    """Tests for delivery docket PDF generation."""

    def setUp(self) -> None:
        self.client_obj = Company.objects.create(
            name="Test Company",
            xero_last_modified=timezone.now(),
        )
        self.job = Job.objects.create(
            company=self.client_obj,
            name="Test Delivery Job",
            description="Deliver some steel",
            staff=self.test_staff,
        )
        # create_delivery_docket_pdf doesn't need workshop hours,
        # but add a minimal estimate so the job is well-formed
        estimate = self.job.cost_sets.filter(kind="estimate").first()
        if estimate:
            CostLine.objects.create(
                cost_set=estimate,
                kind="time",
                labour_subtype=LabourSubtype.objects.get(name="Workshop"),
                desc="Fabrication",
                quantity=Decimal("2.000"),
                unit_cost=Decimal("32.00"),
                unit_rev=Decimal("105.00"),
                accounting_date=timezone.localdate(),
            )

    def test_delivery_docket_is_exactly_two_pages(self) -> None:
        """Delivery docket should be exactly 2 pages: company copy + customer copy."""
        pdf_buffer = create_delivery_docket_pdf(self.job)
        reader = PdfReader(pdf_buffer)
        self.assertEqual(
            len(reader.pages),
            2,
            f"Expected 2 pages (company + customer copy), got {len(reader.pages)}",
        )
