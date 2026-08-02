"""Workshop PDF business rules (ported subset of v1 test_workshop_pdf_service.py).

Rendering bytes are pinned by the golden tests; these tests pin the business
behaviour underneath: production-vs-office labour bucketing, the estimate→
quote fallback, hour formatting, and the Quill-HTML conversion contract.
"""

from decimal import Decimal
from typing import Any

import pytest
from django.apps import apps as django_apps
from django.utils import timezone

from apps.accounts.models import Staff
from apps.company.models import Company
from apps.company.tests.job_fixtures import make_job
from apps.job.models import CostLine, LabourSubtype
from apps.job.models.costing import CostSet
from apps.job.services.workshop_pdf_service import (
    convert_html_to_reportlab,
    format_hours_display,
    get_time_breakdown,
    get_workshop_hours,
)

pytestmark = pytest.mark.django_db


def _add_time(
    staff: Staff, cost_set: CostSet, subtype_name: str, hours: str, desc: str
) -> CostLine:
    kwargs: dict[str, Any] = {}
    today = timezone.localdate()
    if cost_set.kind == "actual":
        xero_pay_item_model = django_apps.get_model("xero", "XeroPayItem")
        kwargs = {
            "staff": staff,
            "xero_pay_item": xero_pay_item_model._default_manager.get(name="Ordinary Time"),
            "meta": {
                "staff_id": str(staff.id),
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


class TestWorkshopHourBreakdown:
    def test_budget_breakdown_skips_office_labour_and_buckets_production(
        self, company: Company, office_staff: Staff
    ) -> None:
        job = make_job(company, office_staff, name="PDF Time Job")
        estimate = job.latest_estimate
        _add_time(office_staff, estimate, "Workshop", "4.000", "Workshop")
        _add_time(office_staff, estimate, "Onsite", "5.000", "Onsite")
        _add_time(office_staff, estimate, "Supervision", "2.000", "Supervision")
        _add_time(office_staff, estimate, "Admin", "3.000", "Admin")
        _add_time(office_staff, estimate, "Quoting", "1.000", "Quoting")

        assert get_workshop_hours(job) == 11.0

        breakdown = get_time_breakdown(job)
        assert breakdown["budgeted_hours"] == 11.0
        subtype_hours = {
            row["name"]: row["estimated_hours"] for row in breakdown["subtype_breakdown"]
        }
        assert subtype_hours == {
            "WORKSHOP TIME": 4.0,
            "Onsite Time": 5.0,
            "Supervision Time": 2.0,
        }
        workshop_rows = [row for row in breakdown["subtype_breakdown"] if row["is_workshop"]]
        assert [row["name"] for row in workshop_rows] == ["WORKSHOP TIME"]

    def test_actual_hours_skip_office_like_subtypes_for_pdf(
        self, company: Company, office_staff: Staff
    ) -> None:
        job = make_job(company, office_staff, name="PDF Actuals Job")
        estimate = job.latest_estimate
        _add_time(office_staff, estimate, "Workshop", "8.000", "Workshop")
        _add_time(office_staff, estimate, "Admin", "2.000", "Admin")

        actual = job.latest_actual
        _add_time(office_staff, actual, "Workshop", "3.000", "Workshop actual")
        _add_time(office_staff, actual, "Admin", "2.000", "Admin actual")

        breakdown = get_time_breakdown(job)

        assert breakdown["used_hours"] == 3.0
        assert breakdown["remaining_hours"] == 5.0
        assert breakdown["production_budgeted_hours"] == 8.0
        assert breakdown["production_used_hours"] == 3.0
        assert breakdown["production_remaining_hours"] == 5.0
        assert breakdown["staff_breakdown"] == [{"name": "Office Staff", "hours": 3.0}]

    def test_zero_estimate_hours_fall_back_to_quote(
        self, company: Company, office_staff: Staff
    ) -> None:
        job = make_job(company, office_staff, name="Quote Fallback Job")
        _add_time(office_staff, job.latest_quote, "Workshop", "6.000", "Quoted workshop")

        assert get_workshop_hours(job) == 6.0

    def test_missing_time_line_subtype_raises_instead_of_hiding_hours(
        self, company: Company, office_staff: Staff
    ) -> None:
        """A time line without subtype must fail visibly, not silently exclude
        those hours from remaining-work calculations."""
        job = make_job(company, office_staff, name="Broken Subtype Job")
        line = _add_time(office_staff, job.latest_estimate, "Workshop", "4.000", "Workshop")
        CostLine.objects.filter(id=line.id).update(labour_subtype=None)

        with pytest.raises(ValueError, match="has no labour subtype"):
            get_workshop_hours(job)


class TestFormatHoursDisplay:
    @pytest.mark.parametrize(
        ("hours", "expected"),
        [
            (2.0, "2h"),
            (2.5, "2h 30m"),
            (0.25, "15m"),
            (0.0, "0h"),
            (None, "0h"),
            (100.0, "100h"),
            (1.999, "2h"),
            (3, "3h"),
        ],
    )
    def test_formats(self, hours: float | None, expected: str) -> None:
        assert format_hours_display(hours) == expected


class TestConvertHtmlToReportlab:
    def test_simple_paragraphs_preserve_line_breaks(self) -> None:
        assert (
            convert_html_to_reportlab("<p>Line one</p><p>Line two</p>") == "Line one<br/>Line two"
        )

    def test_strong_and_em_convert_to_b_and_i(self) -> None:
        assert convert_html_to_reportlab("<p><strong>Bold</strong> text</p>") == "<b>Bold</b> text"
        assert convert_html_to_reportlab("<p><em>Slanty</em></p>") == "<i>Slanty</i>"

    def test_anchor_converts_to_link(self) -> None:
        result = convert_html_to_reportlab('<p><a href="https://x.example">site</a></p>')
        assert result == '<link href="https://x.example">site</link>'

    def test_ordered_list_converts_to_numbered(self) -> None:
        result = convert_html_to_reportlab("<ol><li>First</li><li>Second</li></ol>")
        assert "1. First" in result
        assert "2. Second" in result

    def test_unordered_list_converts_to_bullets(self) -> None:
        result = convert_html_to_reportlab("<ul><li>One</li><li>Two</li></ul>")
        assert "• One" in result
        assert "• Two" in result

    def test_style_attributes_are_stripped(self) -> None:
        result = convert_html_to_reportlab('<p><span style="color: red;">Danger</span></p>')
        assert result == "Danger"

    def test_empty_and_none_return_na(self) -> None:
        assert convert_html_to_reportlab("") == "N/A"
        assert convert_html_to_reportlab("<p></p>") == "N/A"

    def test_quill_ui_spans_removed(self) -> None:
        result = convert_html_to_reportlab('<p><span class="ql-ui">x</span>Content</p>')
        assert result == "Content"
