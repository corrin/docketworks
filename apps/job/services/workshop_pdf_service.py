import logging
import os
import re
import time
from collections import defaultdict
from html import escape
from io import BytesIO
from typing import Callable, Optional, Union, cast
from uuid import UUID

from bs4 import BeautifulSoup, NavigableString
from django.conf import settings
from django.db.models import OuterRef, Prefetch, Subquery
from django.utils import timezone
from PIL import Image, ImageFile
from pypdf import PdfWriter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from reportlab.platypus import Flowable, Paragraph, Table, TableStyle

from apps.company.models import ClientContactMethod
from apps.crm.models import PhoneEndpoint
from apps.job.enums import SpeedQualityTradeoff
from apps.job.models import CostLine, CostSet, Job, JobFile
from apps.workflow.exceptions import AlreadyLoggedException
from apps.workflow.models import CompanyDefaults
from apps.workflow.services.error_persistence import persist_and_raise

logger = logging.getLogger(__name__)

JOB_SUMMARY_PDF_FILENAME = "JobSummary.pdf"
WORKSHOP_PDF_COST_LINES_ATTR = "_workshop_pdf_cost_lines"
WORKSHOP_PDF_FILES_ATTR = "_workshop_pdf_files_to_print"
WORKSHOP_PDF_CONTACT_PHONE_ATTR = "_workshop_pdf_contact_phone"
WORKSHOP_PDF_COMPANY_PHONE_ATTR = "_workshop_pdf_company_phone"


def _primary_phone_for_job(job: Job) -> str:
    """Phone to print on workshop docs and delivery dockets.

    Display preference order: the job contact's own number first, falling back
    to the company's number when the contact has no phone method (the business
    rule carried over from the pre-ClientContactMethod scalar fields).
    """
    if not hasattr(job, WORKSHOP_PDF_CONTACT_PHONE_ATTR) or not hasattr(
        job, WORKSHOP_PDF_COMPANY_PHONE_ATTR
    ):
        raise ValueError("PDF phone fields must be loaded before rendering")

    contact_phone = getattr(job, WORKSHOP_PDF_CONTACT_PHONE_ATTR)
    if contact_phone:
        return str(contact_phone)
    return str(getattr(job, WORKSHOP_PDF_COMPANY_PHONE_ATTR) or "")


def _primary_company_endpoint_number() -> str:
    endpoint = (
        PhoneEndpoint.objects.filter(
            is_active=True,
            endpoint_type=PhoneEndpoint.EndpointType.MAIN_LINE,
        )
        .order_by("label", "normalized_number")
        .first()
    )
    return endpoint.number if endpoint else ""


def _primary_phone_annotations() -> dict[str, Subquery]:
    contact_phone = (
        ClientContactMethod.objects.filter(
            method_type=ClientContactMethod.MethodType.PHONE,
            contact_id=OuterRef("contact_id"),
        )
        .order_by("-is_primary", "label", "value")
        .values("value")[:1]
    )
    company_phone = (
        ClientContactMethod.objects.filter(
            method_type=ClientContactMethod.MethodType.PHONE,
            company_id=OuterRef("company_id"),
        )
        .order_by("-is_primary", "label", "value")
        .values("value")[:1]
    )
    return {
        WORKSHOP_PDF_CONTACT_PHONE_ATTR: Subquery(contact_phone),
        WORKSHOP_PDF_COMPANY_PHONE_ATTR: Subquery(company_phone),
    }


def get_job_for_delivery_docket_pdf(job_id: UUID) -> Job:
    """Load a job with the relations required to render a delivery docket."""
    return cast(
        Job,
        Job.objects.select_related("company", "contact")
        .annotate(**_primary_phone_annotations())
        .get(id=job_id),
    )


def get_job_for_workshop_pdf(job_id: UUID) -> Job:
    """Load a job with the relations required to render a workshop PDF."""
    cost_lines = CostLine.objects.select_related("staff", "labour_subtype").order_by(
        "kind", "-quantity", "-created_at", "-id"
    )
    files_to_print = (
        JobFile.objects.filter(print_on_jobsheet=True)
        .exclude(filename=JOB_SUMMARY_PDF_FILENAME)
        .order_by("-uploaded_at")
    )
    return cast(
        Job,
        Job.objects.select_related(
            "company",
            "contact",
            "latest_estimate",
            "latest_quote",
            "latest_actual",
        )
        .annotate(**_primary_phone_annotations())
        .prefetch_related(
            # Prefetch cost lines for all three cost sets uniformly. The quote is
            # only read on the rare zero-estimate-hours fallback, so its prefetch
            # is sometimes unused — that is a deliberate, cheap (~5 rows) eager
            # load, whitelisted in settings.NPLUSONE_WHITELIST so nplusone does
            # not raise on it under CELERY_TASK_ALWAYS_EAGER.
            Prefetch(
                "latest_estimate__cost_lines",
                queryset=cost_lines,
                to_attr=WORKSHOP_PDF_COST_LINES_ATTR,
            ),
            Prefetch(
                "latest_quote__cost_lines",
                queryset=cost_lines,
                to_attr=WORKSHOP_PDF_COST_LINES_ATTR,
            ),
            Prefetch(
                "latest_actual__cost_lines",
                queryset=cost_lines,
                to_attr=WORKSHOP_PDF_COST_LINES_ATTR,
            ),
            Prefetch(
                "files",
                queryset=files_to_print,
                to_attr=WORKSHOP_PDF_FILES_ATTR,
            ),
        )
        .get(id=job_id),
    )


def _ensure_workshop_pdf_job_loaded(job: Job) -> Job:
    if hasattr(job, WORKSHOP_PDF_FILES_ATTR) and hasattr(
        job.latest_actual, WORKSHOP_PDF_COST_LINES_ATTR
    ):
        return job
    return get_job_for_workshop_pdf(job.id)


def _ensure_delivery_docket_pdf_job_loaded(job: Job) -> Job:
    if hasattr(job, WORKSHOP_PDF_CONTACT_PHONE_ATTR) and hasattr(
        job, WORKSHOP_PDF_COMPANY_PHONE_ATTR
    ):
        return job
    return get_job_for_delivery_docket_pdf(job.id)


def _cost_lines_for_pdf(cost_set: CostSet) -> list[CostLine]:
    prefetched = getattr(cost_set, WORKSHOP_PDF_COST_LINES_ATTR, None)
    if prefetched is not None:
        return list(prefetched)
    return list(
        CostLine.objects.filter(cost_set_id=cost_set.id)
        .select_related("staff", "labour_subtype")
        .order_by("kind", "-quantity", "-created_at", "-id")
    )


def _production_time_lines(cost_set: CostSet) -> list[CostLine]:
    lines: list[CostLine] = []
    for line in _cost_lines_for_pdf(cost_set):
        if line.kind != "time":
            continue
        if line.labour_subtype is None:
            raise ValueError(f"CostLine {line.id} has no labour subtype")
        if line.labour_subtype.counts_for_scheduling:
            lines.append(line)
        else:
            pass  # Office/admin-like labour does not consume production capacity.
    return lines


def _printable_job_files(job: Job) -> list[JobFile]:
    prefetched = getattr(job, WORKSHOP_PDF_FILES_ATTR, None)
    if prefetched is not None:
        return list(prefetched)
    return list(
        JobFile.objects.filter(job_id=job.id, print_on_jobsheet=True)
        .exclude(filename=JOB_SUMMARY_PDF_FILENAME)
        .order_by("-uploaded_at")
    )


def format_hours_display(hours: Optional[float]) -> str:
    """Format hours as human-readable 'Xh Ym' string."""
    if hours is None or not isinstance(hours, (int, float)):
        return "0h"
    total_minutes = round(hours * 60)
    h = total_minutes // 60
    m = total_minutes % 60
    if h == 0 and m == 0:
        return "0h"
    if h == 0:
        return f"{m}m"
    if m == 0:
        return f"{h}h"
    return f"{h}h {m}m"


def format_hours_compact(hours: float) -> str:
    """Format hours as H:MM for tight PDF summary rows."""
    total_minutes = round(hours * 60)
    h = total_minutes // 60
    m = total_minutes % 60
    return f"{h}:{m:02d}"


def format_retail_line_total(line: CostLine) -> str:
    """Format material retail line total, leaving unknown retail prices blank."""
    if line.unit_rev == 0:
        return ""
    return f"${line.quantity * line.unit_rev:.2f}"


def get_workshop_hours(job: Job) -> float:
    """
    Calculate production time allocated from the latest estimate or quote.

    Sums time CostLines whose labour subtype consumes schedulable staff capacity.
    Falls back to quote if estimate has zero workshop hours.
    """
    estimate = job.latest_estimate
    if estimate is None:
        exc = ValueError(f"Job {job.job_number} has no estimate CostSet")
        raise exc

    workshop_hours = _workshop_time_total(estimate)

    if workshop_hours <= 0:
        quote = job.latest_quote
        if quote is None:
            exc = ValueError(
                f"Job {job.job_number} has no quote CostSet to fall back to"
            )
            raise exc

        workshop_hours = _workshop_time_total(quote)

    return workshop_hours


def _workshop_time_total(cost_set: CostSet) -> float:
    total = sum(line.quantity for line in _production_time_lines(cost_set))
    return float(total)


def _production_time_by_bucket(
    cost_set: CostSet,
) -> dict[str, dict[str, bool | float | str]]:
    buckets: dict[str, dict[str, bool | float | str]] = {}
    for line in _production_time_lines(cost_set):
        labour_subtype = line.labour_subtype
        if labour_subtype is None:
            exc = ValueError(f"CostLine {line.id} has no labour subtype")
            raise exc
        bucket_id = str(labour_subtype.id)
        bucket = buckets.setdefault(
            bucket_id,
            {
                "name": (
                    "WORKSHOP TIME"
                    if labour_subtype.is_workshop
                    else f"{labour_subtype.name} Time"
                ),
                "hours": 0.0,
                "is_workshop": labour_subtype.is_workshop,
            },
        )
        bucket["hours"] = float(bucket["hours"]) + float(line.quantity)
    buckets = dict(
        sorted(
            buckets.items(),
            key=lambda item: (
                not bool(item[1]["is_workshop"]),
                str(item[1]["name"]),
            ),
        )
    )
    return buckets


def _latest_budget_cost_set(job: Job) -> CostSet:
    estimate = job.latest_estimate
    if estimate is None:
        exc = ValueError(f"Job {job.job_number} has no estimate CostSet")
        raise exc

    if _workshop_time_total(estimate) > 0:
        return estimate

    quote = job.latest_quote
    if quote is None:
        exc = ValueError(f"Job {job.job_number} has no quote CostSet to fall back to")
        raise exc
    return quote


def get_time_breakdown(job: Job) -> dict:
    """
    Get detailed time breakdown for workshop PDF.

    Returns:
        dict with keys:
            - budgeted_hours: Production labour hours from estimate/quote
            - used_hours: Production labour hours from latest_actual
            - remaining_hours: Difference
            - is_over_budget: True if over budget
            - staff_breakdown: List of dicts with staff name and hours worked
            - subtype_breakdown: List of dicts with workshop/other production hours
    """
    budget_cost_set = _latest_budget_cost_set(job)
    budgeted_by_subtype = _production_time_by_bucket(budget_cost_set)
    budgeted_hours = sum(float(item["hours"]) for item in budgeted_by_subtype.values())
    used_hours = 0.0
    production_budgeted_hours = _workshop_time_total(budget_cost_set)
    production_used_hours = 0.0
    staff_breakdown = []
    used_by_subtype: dict[str, dict[str, bool | float | str]] = {}

    # Get used hours and staff breakdown from actual
    if job.latest_actual:
        used_by_subtype = _production_time_by_bucket(job.latest_actual)
        used_hours = sum(float(item["hours"]) for item in used_by_subtype.values())
        production_used_hours = _workshop_time_total(job.latest_actual)

        # Get breakdown by staff member
        time_lines = _production_time_lines(job.latest_actual)

        # Group by staff
        staff_hours = defaultdict(float)
        for line in time_lines:
            staff = line.staff
            if staff is None:
                exc = ValueError(
                    f"CostLine {line.id} for job {job.job_number} has no staff set"
                )
                raise exc

            staff_name = f"{staff.first_name} {staff.last_name}"
            staff_hours[staff_name] += float(line.quantity)

        # Convert to list of dicts sorted by hours descending
        staff_breakdown = [
            {"name": name, "hours": hours}
            for name, hours in sorted(
                staff_hours.items(), key=lambda x: x[1], reverse=True
            )
        ]

    subtype_ids = list(budgeted_by_subtype)
    subtype_ids.extend(
        subtype_id for subtype_id in used_by_subtype if subtype_id not in subtype_ids
    )
    subtype_breakdown = []
    for subtype_id in subtype_ids:
        budgeted_item = budgeted_by_subtype.get(subtype_id)
        used_item = used_by_subtype.get(subtype_id)
        name = str((budgeted_item or used_item or {"name": "WORKSHOP TIME"})["name"])
        estimated = float((budgeted_item or {"hours": 0.0})["hours"])
        used = float((used_item or {"hours": 0.0})["hours"])
        is_workshop = bool(
            (budgeted_item or used_item or {"is_workshop": False})["is_workshop"]
        )
        if estimated == 0 and used == 0:
            continue
        subtype_breakdown.append(
            {
                "name": name,
                "estimated_hours": estimated,
                "used_hours": used,
                "remaining_hours": estimated - used,
                "is_workshop": is_workshop,
            }
        )

    remaining_hours = budgeted_hours - used_hours
    is_over_budget = used_hours > budgeted_hours and budgeted_hours > 0
    production_remaining_hours = production_budgeted_hours - production_used_hours

    return {
        "budgeted_hours": budgeted_hours,
        "used_hours": used_hours,
        "remaining_hours": remaining_hours,
        "production_budgeted_hours": production_budgeted_hours,
        "production_used_hours": production_used_hours,
        "production_remaining_hours": production_remaining_hours,
        "is_over_budget": is_over_budget,
        "staff_breakdown": staff_breakdown,
        "subtype_breakdown": subtype_breakdown,
    }


# Page metrics (A4: 210 x 297 mm)
PAGE_WIDTH, PAGE_HEIGHT = A4
MARGIN = 50
CONTENT_WIDTH = PAGE_WIDTH - (2 * MARGIN)

LOGO_BOX = 150
WORKSHOP_LOGO_HEIGHT = 52

styles = getSampleStyleSheet()

# Palette and typography
PRIMARY = colors.HexColor("#004AAD")
TEXT_DARK = colors.HexColor("#0F172A")
TEXT_MUTED = colors.HexColor("#334155")
BORDER = colors.HexColor("#CBD5E1")
ROW_ALT = colors.HexColor("#F8FAFC")

# Paragraph styles for table content
header_company_style = ParagraphStyle(
    "HeaderCompany",
    parent=styles["Normal"],
    fontName="Helvetica-Bold",
    fontSize=18,
    leading=22,
    textColor=colors.white,
    spaceAfter=0,
)

header_contact_style = ParagraphStyle(
    "HeaderContact",
    parent=styles["Normal"],
    fontName="Helvetica-Bold",
    fontSize=14,
    leading=18,
    textColor=colors.white,
    spaceAfter=0,
)

label_style = ParagraphStyle(
    "Label",
    parent=styles["Normal"],
    fontName="Helvetica-Bold",
    fontSize=10,
    leading=14,
    textColor=TEXT_MUTED,
    spaceAfter=0,
)

body_style = ParagraphStyle(
    "Body",
    parent=styles["Normal"],
    fontName="Helvetica",
    fontSize=10,
    leading=14,
    textColor=TEXT_DARK,
)

brief_label_style = ParagraphStyle(
    "BriefLabel",
    parent=label_style,
    fontSize=8,
    leading=10,
)

brief_label_inverse_style = ParagraphStyle(
    "BriefLabelInverse",
    parent=brief_label_style,
    textColor=colors.white,
)

brief_value_style = ParagraphStyle(
    "BriefValue",
    parent=body_style,
    fontSize=10,
    leading=12,
)

brief_value_bold_style = ParagraphStyle(
    "BriefValueBold",
    parent=brief_value_style,
    fontName="Helvetica-Bold",
)

section_label_style = ParagraphStyle(
    "SectionLabel",
    parent=label_style,
    fontSize=11,
    leading=13,
)

# Keep the public name expected elsewhere in the file
description_style = body_style

ImageFile.LOAD_TRUNCATED_IMAGES = True


def _advance_to_new_page(
    pdf: canvas.Canvas,
    margin: float = MARGIN,
    on_new_page: Optional[Callable[[canvas.Canvas], float]] = None,
) -> float:
    """
    Advance the canvas to a new page and return the refreshed y position.
    Optionally execute a callback to draw repeated headers before continuing.
    """
    pdf.showPage()
    if on_new_page:
        return on_new_page(pdf)
    return PAGE_HEIGHT - margin


def draw_table_with_page_breaks(
    pdf: canvas.Canvas,
    table: Table,
    y_position: float,
    *,
    x_position: float = MARGIN,
    margin: float = MARGIN,
    available_width: float = CONTENT_WIDTH,
    on_new_page: Optional[Callable[[canvas.Canvas], float]] = None,
) -> float:
    """
    Draw a table across one or more pages, returning the updated y position.

    Handles page breaks when the table would overflow the remaining vertical space.
    """
    pending_parts = [table]

    while pending_parts:
        current_table = pending_parts.pop(0)

        while True:
            available_height = y_position - margin
            if available_height <= 0:
                y_position = _advance_to_new_page(pdf, margin, on_new_page)
                available_height = y_position - margin

            parts = current_table.split(available_width, available_height)
            if not parts:
                y_position = _advance_to_new_page(pdf, margin, on_new_page)
                available_height = y_position - margin
                parts = current_table.split(available_width, available_height)
                if not parts:
                    # If nothing fits even on a fresh page, force-draw to avoid an infinite loop.
                    _, forced_height = current_table.wrapOn(
                        pdf, available_width, available_height
                    )
                    current_table.drawOn(pdf, x_position, y_position - forced_height)
                    y_position -= forced_height
                    pending_parts.clear()
                    break

            current_part = parts[0]
            _, part_height = current_part.wrapOn(pdf, available_width, available_height)
            current_part.drawOn(pdf, x_position, y_position - part_height)
            y_position -= part_height

            remaining_parts = parts[1:]
            if not remaining_parts:
                break

            # Queue remaining chunks (if any) and advance to a fresh page before continuing.
            pending_parts = remaining_parts + pending_parts
            y_position = _advance_to_new_page(pdf, margin, on_new_page)
            break

    return y_position


def wait_until_file_ready(file_path, max_wait=10):
    """Wait until the file is readable, up to max_wait seconds."""
    wait_time = 0
    while wait_time < max_wait:
        try:
            with open(file_path, "rb") as f:
                f.read(10)
            return
        except OSError:
            time.sleep(1)
            wait_time += 1


def _fit_dimensions(
    image_path: str, max_width: float, max_height: float
) -> tuple[float, float]:
    """Return (width_pt, height_pt) to draw the image inside
    (max_width, max_height) preserving aspect ratio. The on-page footprint
    is determined by the bounding box, not by the source pixel count."""
    wait_until_file_ready(image_path)
    with Image.open(image_path) as img:
        w, h = img.size
    scale = min(max_width / w, max_height / h)
    return w * scale, h * scale


def convert_html_to_reportlab(html_content):
    """
    Convert Quill HTML to ReportLab-friendly inline markup, with list support.

    Uses BeautifulSoup for proper HTML parsing instead of regex to avoid
    edge cases like <br> being matched as <b> tags.
    """
    if not html_content:
        return "N/A"

    # Tags that ReportLab Paragraph supports (we keep these)
    ALLOWED_TAGS = {"b", "i", "u", "strike", "link", "font", "br"}

    try:
        # Use html.parser for forgiving parsing of user-pasted content
        soup = BeautifulSoup(html_content, "html.parser")

        # Remove Quill UI elements entirely (including content)
        for span in soup.find_all("span", class_="ql-ui"):
            span.decompose()

        # Process headings (h1-h4) -> font size + bold
        heading_sizes = {"h1": 18, "h2": 16, "h3": 14, "h4": 13}
        for heading, size in heading_sizes.items():
            for tag in soup.find_all(heading):
                new_content = soup.new_tag("font", size=str(size))
                b_tag = soup.new_tag("b")
                b_tag.extend(tag.contents[:])
                new_content.append(b_tag)
                tag.replace_with(new_content)
                new_content.insert_after(NavigableString("\n"))

        # Process blockquotes -> italic
        for tag in soup.find_all("blockquote"):
            new_tag = soup.new_tag("i")
            new_tag.extend(tag.contents[:])
            tag.replace_with(new_tag)
            new_tag.insert_after(NavigableString("\n"))

        # Process pre -> Courier font
        for tag in soup.find_all("pre"):
            new_tag = soup.new_tag("font", face="Courier")
            new_tag.extend(tag.contents[:])
            tag.replace_with(new_tag)
            new_tag.insert_after(NavigableString("\n"))

        # Process lists (ol, ul) - must process before unwrapping other tags
        for ol in soup.find_all("ol"):
            items = ol.find_all("li", recursive=False)
            replacement = NavigableString("\n")
            for i, li in enumerate(items):
                prefix = f"{i + 1}. "
                li_content = "".join(str(c) for c in li.contents)
                replacement = NavigableString(
                    str(replacement) + prefix + li_content + "\n"
                )
            ol.replace_with(replacement)

        for ul in soup.find_all("ul"):
            items = ul.find_all("li", recursive=False)
            replacement = NavigableString("\n")
            for li in items:
                li_content = "".join(str(c) for c in li.contents)
                replacement = NavigableString(
                    str(replacement) + "• " + li_content + "\n"
                )
            ul.replace_with(replacement)

        # Process paragraph tags - insert newline after each <p> before unwrapping
        # Quill editor uses <p> tags for each line, so we need to preserve line breaks
        for tag in soup.find_all("p"):
            tag.insert_after(NavigableString("\n"))

        # Convert inline formatting tags to ReportLab equivalents
        for tag in soup.find_all("strong"):
            tag.name = "b"
        for tag in soup.find_all("em"):
            tag.name = "i"
        for tag in soup.find_all("s"):
            tag.name = "strike"

        # Convert <a href="..."> to <link href="...">
        for tag in soup.find_all("a"):
            href = tag.get("href", "")
            tag.name = "link"
            tag.attrs = {"href": href} if href else {}

        # Strip all attributes from allowed tags (except link which keeps href)
        for tag in soup.find_all(["b", "i", "u", "strike", "font", "br"]):
            if tag.name == "font":
                # Keep only size and face attributes for font
                tag.attrs = {
                    k: v for k, v in tag.attrs.items() if k in ("size", "face")
                }
            else:
                tag.attrs = {}

        # Unwrap (remove tag, keep content) any tags not in ALLOWED_TAGS
        # Use list() to avoid modifying while iterating
        for tag in list(soup.find_all(True)):
            if tag.name not in ALLOWED_TAGS:
                tag.unwrap()

        # Convert to string - BeautifulSoup renders <br> as <br/>
        result = str(soup)

        # Convert all newlines to line breaks (preserves paragraph structure from <p> tags)
        result = result.replace("\n", "<br/>")

        # Collapse excessive line breaks (3+ becomes 2 for paragraph spacing)
        result = re.sub(r"(<br/>){3,}", "<br/><br/>", result)
        result = re.sub(r"(<br/>)+$", "", result)
        result = result.strip()

        return result if result else "N/A"

    except Exception as exc:
        logger.error(
            "Failed to convert HTML to ReportLab markup: %s. Input: %s",
            exc,
            html_content[:200] if html_content else "",
        )
        raise


def create_workshop_pdf(job: Job) -> BytesIO:
    """
    Generate the workshop PDF with materials table and attachments.
    """
    try:
        job = _ensure_workshop_pdf_job_loaded(job)
        main_buffer = create_workshop_main_document(job)

        files_to_print = _printable_job_files(job)
        if not files_to_print:
            return main_buffer

        image_files = [f for f in files_to_print if f.mime_type.startswith("image/")]
        pdf_files = [f for f in files_to_print if f.mime_type == "application/pdf"]

        return process_attachments(main_buffer, image_files, pdf_files)
    except AlreadyLoggedException:
        raise
    except Exception as exc:
        logger.error("Error creating workshop PDF: %s", exc)
        persist_and_raise(exc, job_id=str(job.id))
        raise AssertionError("persist_and_raise returned unexpectedly")


def create_delivery_docket_pdf(job: Job) -> BytesIO:
    """
    Generate a delivery docket PDF (no materials, workshop time, or internal notes).
    Includes handover section with signature, date, and notes fields.
    Does not include job attachments - delivery dockets are kept minimal.
    """
    try:
        job = _ensure_delivery_docket_pdf_job_loaded(job)
        return create_delivery_docket_main_document(job)
    except Exception as e:
        logger.error(f"Error creating delivery docket PDF: {str(e)}")
        raise e


def create_workshop_main_document(job: Job) -> BytesIO:
    """Create the workshop cover document with header, details, time used, and materials tables."""
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)

    y_position = PAGE_HEIGHT - MARGIN
    y_position = add_workshop_letterhead(pdf, y_position)
    y_position = add_title(pdf, y_position, job)
    y_position = add_workshop_details_table(pdf, y_position, job)
    pdf.showPage()
    y_position = PAGE_HEIGHT - MARGIN
    y_position = add_time_used_table(pdf, y_position, job)
    y_position = add_materials_used_table(pdf, y_position, job)

    pdf.save()
    buffer.seek(0)
    return buffer


def create_delivery_docket_main_document(job: Job) -> BytesIO:
    """Create the delivery docket document with two copies: Company Copy and Customer Copy."""
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)

    # Get company acronym for copy labels
    company = CompanyDefaults.get_solo()
    copy_label = (
        f"{company.company_acronym} Copy" if company.company_acronym else "Office Copy"
    )

    # First page - Company Copy
    y_position = PAGE_HEIGHT - MARGIN
    y_position = add_letterhead_banner(pdf, y_position)
    y_position = add_title(
        pdf, y_position, job, title_prefix=f"DELIVERY DOCKET - {copy_label}"
    )
    y_position = add_delivery_docket_details_table(pdf, y_position, job)
    add_handover_section(pdf, job)

    # Start new page for Customer Copy
    pdf.showPage()

    # Second page - Customer Copy
    y_position = PAGE_HEIGHT - MARGIN
    y_position = add_letterhead_banner(pdf, y_position)
    y_position = add_title(
        pdf, y_position, job, title_prefix="DELIVERY DOCKET - Customer Copy"
    )
    y_position = add_delivery_docket_details_table(pdf, y_position, job)
    add_handover_section(pdf, job)

    pdf.save()
    buffer.seek(0)
    return buffer


def add_logo(pdf: canvas.Canvas, y_position: float) -> float:
    """Draw the square logo centred at the top and return the updated y position."""
    company = CompanyDefaults.get_solo()
    if not company.logo:
        raise ValueError("No logo uploaded in Company Defaults")
    w, h = _fit_dimensions(company.logo.path, LOGO_BOX, LOGO_BOX)
    logo = ImageReader(company.logo.path)
    x = MARGIN + (CONTENT_WIDTH - w) / 2
    pdf.drawImage(logo, x, y_position - h, width=w, height=h, mask="auto")
    return y_position - h - 24


def add_workshop_letterhead(pdf: canvas.Canvas, y_position: float) -> float:
    """Draw a compact wide logo for the workshop job sheet."""
    company = CompanyDefaults.get_solo()
    if company.logo_wide:
        with Image.open(company.logo_wide.path) as img:
            src_w, src_h = img.size
        width = WORKSHOP_LOGO_HEIGHT * (src_w / src_h)
        width = min(width, CONTENT_WIDTH)
        logo = ImageReader(company.logo_wide.path)
        x = MARGIN + (CONTENT_WIDTH - width) / 2
        pdf.drawImage(
            logo,
            x,
            y_position - WORKSHOP_LOGO_HEIGHT,
            width=width,
            height=WORKSHOP_LOGO_HEIGHT,
            mask="auto",
        )
        return y_position - WORKSHOP_LOGO_HEIGHT - 20

    return add_logo(pdf, y_position)


def add_letterhead_banner(pdf, y_position):
    """Draw the wide letterhead banner and company contact details below it."""
    company = CompanyDefaults.get_solo()
    if not company.logo_wide:
        raise ValueError("No wide logo uploaded in Company Defaults")
    with Image.open(company.logo_wide.path) as img:
        src_w, src_h = img.size
    img_width_pt = CONTENT_WIDTH
    img_height_pt = src_h * (CONTENT_WIDTH / src_w)
    banner = ImageReader(company.logo_wide.path)
    banner_top = PAGE_HEIGHT - MARGIN
    pdf.drawImage(
        banner,
        MARGIN,
        banner_top - img_height_pt,
        width=img_width_pt,
        height=img_height_pt,
        mask="auto",
    )

    # Company contact details below the banner
    contact_y = banner_top - img_height_pt - 12
    pdf.setFont("Helvetica", 8)
    pdf.setFillColor(TEXT_MUTED)

    # Left side: address
    address_parts = [
        p for p in [company.address_line1, company.address_line2, company.city] if p
    ]
    if company.post_code and address_parts:
        address_parts[-1] = f"{address_parts[-1]} {company.post_code}"
    pdf.drawString(MARGIN, contact_y, ", ".join(address_parts))

    # Right side: phone and email
    right_parts = [
        p for p in [_primary_company_endpoint_number(), company.company_email] if p
    ]
    if right_parts:
        pdf.drawRightString(PAGE_WIDTH - MARGIN, contact_y, "    ".join(right_parts))

    return contact_y - 35


def _wrap_text_for_canvas(
    pdf: canvas.Canvas, text: str, max_width: float, font_name: str, font_size: int
) -> list[str]:
    """
    Wrap text to fit inside max_width based on actual font metrics.
    """
    if not text:
        return [""]

    pdf.setFont(font_name, font_size)
    words = text.split()
    if not words:
        return [""]

    lines = []
    current_line = words[0]
    for word in words[1:]:
        candidate = f"{current_line} {word}".strip()
        if pdf.stringWidth(candidate, font_name, font_size) <= max_width:
            current_line = candidate
        else:
            lines.append(current_line)
            current_line = word
    lines.append(current_line)
    return lines


def add_title(
    pdf: canvas.Canvas,
    y_position: float,
    job: Job,
    title_prefix: Optional[str] = None,
) -> float:
    """
    Render the job title with consistent palette.

    Args:
        pdf: The canvas object
        y_position: Current vertical position
        job: The Job instance
        title_prefix: Optional prefix to add before "Job - {number} - {name}"
    """
    font_name = "Helvetica-Bold"
    font_size = 18
    line_height = font_size + 6

    pdf.setFillColor(PRIMARY)
    pdf.setFont(font_name, font_size)
    job_number = str(job.job_number) if job.job_number else "N/A"
    job_name = job.name or "N/A"
    job_line = f"Job - {job_number} - {job_name}"
    current_y = y_position

    if title_prefix:
        prefix_lines = _wrap_text_for_canvas(
            pdf, title_prefix, CONTENT_WIDTH, font_name, font_size
        )
        for line in prefix_lines:
            pdf.drawString(MARGIN, current_y, line)
            current_y -= line_height

    job_lines = _wrap_text_for_canvas(
        pdf, job_line, CONTENT_WIDTH, font_name, font_size
    )
    for line in job_lines:
        pdf.drawString(MARGIN, current_y, line)
        current_y -= line_height

    pdf.setFillColor(colors.black)
    return current_y - 4


def add_time_used_table(pdf: canvas.Canvas, y_position: float, job: Job) -> float:
    """
    Render the time used table showing staff members and hours worked,
    similar to the materials notes table.

    Returns the updated y_position after drawing the table.
    """
    time_breakdown = get_time_breakdown(job)

    # Build table data - header row + actual time entries + 5 blank rows
    time_data = [["STAFF MEMBER", "HOURS", "REMAINING"]]

    # Calculate running remaining hours
    budgeted = time_breakdown["production_budgeted_hours"]
    used_so_far = 0.0

    # Add actual time entries
    for staff_entry in time_breakdown["staff_breakdown"]:
        used_so_far += staff_entry["hours"]
        remaining = budgeted - used_so_far
        time_data.append(
            [
                staff_entry["name"],
                format_hours_display(staff_entry["hours"]),
                format_hours_display(remaining),
            ]
        )
    total_row_number = len(time_data)
    time_data.append(
        [
            "Total",
            format_hours_display(used_so_far),
            format_hours_display(budgeted - used_so_far),
        ]
    )

    # Always add 5 blank rows for handwritten entries
    for _ in range(5):
        time_data.append(["", "", ""])

    time_table = Table(
        time_data,
        colWidths=[CONTENT_WIDTH * 0.5, CONTENT_WIDTH * 0.25, CONTENT_WIDTH * 0.25],
    )
    time_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), PRIMARY),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                ("TOPPADDING", (0, 0), (-1, 0), 8),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ROW_ALT]),
                ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 1), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 1), (-1, -1), 10),
                (
                    "FONTNAME",
                    (0, total_row_number),
                    (-1, total_row_number),
                    "Helvetica-Bold",
                ),
                (
                    "LINEABOVE",
                    (0, total_row_number),
                    (-1, total_row_number),
                    0.75,
                    BORDER,
                ),
            ]
        )
    )

    # Calculate minimum space needed (similar to materials table)
    # Heading: 14pt + 25pt spacing = 39pt
    # Header row: ~29pt
    # Data rows: ~31pt each
    num_rows = len(time_data) - 1  # Exclude header
    min_space_needed = 39 + 29 + (num_rows * 31)
    if y_position - min_space_needed <= MARGIN:
        y_position = _advance_to_new_page(pdf)

    pdf.setFont("Helvetica-Bold", 14)
    pdf.setFillColor(TEXT_DARK)
    pdf.drawString(MARGIN, y_position, "Time Used")
    y_position -= 25

    y_position = draw_table_with_page_breaks(pdf, time_table, y_position)

    if y_position - 20 <= MARGIN:
        return _advance_to_new_page(pdf)

    return y_position - 20


def _plain_paragraph(text: object, style: ParagraphStyle) -> Paragraph:
    return Paragraph(escape(str(text or "N/A")), style)


def _remaining_hours_text(hours: float) -> str:
    if hours < 0:
        return f"{format_hours_display(abs(hours))} over"
    return f"{format_hours_display(hours)} remaining"


def _approval_age_display(job: Job) -> str:
    approved_at = job.accepted_for_work_at
    if not approved_at:
        return "N/A"

    approved_date = timezone.localtime(
        approved_at, timezone.get_current_timezone()
    ).date()
    today = timezone.localdate()
    days = max((today - approved_date).days, 0)
    if days == 0:
        return "Today"
    if days == 1:
        return "1 day ago"
    return f"{days} days ago"


def _draw_table(pdf: canvas.Canvas, table: Table, y_position: float) -> float:
    _, height = table.wrapOn(pdf, CONTENT_WIDTH, y_position - MARGIN)
    table.drawOn(pdf, MARGIN, y_position - height)
    return y_position - height


def _draw_spec_section(
    pdf: canvas.Canvas,
    y_position: float,
    label: str,
    content: str,
) -> float:
    """Draw a labelled workshop spec section, splitting content across pages."""
    label_width = 150
    value_width = CONTENT_WIDTH - label_width
    padding = 8
    min_row_height = 44
    remaining: list[Flowable] = [Paragraph(content, body_style)]
    is_continuation = False

    while remaining:
        if y_position - min_row_height <= MARGIN:
            y_position = _advance_to_new_page(pdf)

        available_height = y_position - MARGIN - (padding * 2)
        available_value_width = value_width - (padding * 2)
        parts = remaining[0].split(available_value_width, available_height)
        if not parts:
            y_position = _advance_to_new_page(pdf)
            available_height = y_position - MARGIN - (padding * 2)
            parts = remaining[0].split(available_value_width, available_height)
            if not parts:
                parts = [remaining[0]]

        part = parts[0]
        remaining = list(parts[1:]) + remaining[1:]

        _, part_height = part.wrap(available_value_width, available_height)
        label_text = f"{label} (CONT.)" if is_continuation else label
        label_paragraph = _plain_paragraph(label_text, section_label_style)
        _, label_height = label_paragraph.wrap(label_width - (padding * 2), part_height)
        row_height = max(part_height, label_height) + (padding * 2)

        y_bottom = y_position - row_height
        pdf.setFillColor(ROW_ALT)
        pdf.rect(MARGIN, y_bottom, label_width, row_height, fill=1, stroke=0)
        pdf.setStrokeColor(BORDER)
        pdf.rect(MARGIN, y_bottom, CONTENT_WIDTH, row_height, fill=0, stroke=1)
        pdf.line(MARGIN + label_width, y_bottom, MARGIN + label_width, y_position)

        label_paragraph.drawOn(
            pdf,
            MARGIN + padding,
            y_position - padding - label_height,
        )
        part.drawOn(
            pdf,
            MARGIN + label_width + padding,
            y_position - padding - part_height,
        )

        y_position = y_bottom
        is_continuation = True

    return y_position - 8


def add_workshop_details_table(
    pdf: canvas.Canvas, y_position: float, job: Job
) -> float:
    """Render a full-page workshop brief: identity, constraints, labour budget, and specs."""
    company_name = job.company.name if job.company else "N/A"
    contact_name = job.contact.name if job.contact else ""
    contact_phone = _primary_phone_for_job(job)
    contact_info = (
        f"{escape(contact_name)}<br/>{escape(contact_phone)}"
        if contact_phone
        else escape(contact_name or "N/A")
    )

    contact_table = Table(
        [
            [
                _plain_paragraph(company_name, header_company_style),
                Paragraph(contact_info, header_contact_style),
            ]
        ],
        colWidths=[CONTENT_WIDTH * 0.42, CONTENT_WIDTH * 0.58],
    )
    contact_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), PRIMARY),
                ("TEXTCOLOR", (0, 0), (-1, -1), colors.white),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    y_position = _draw_table(pdf, contact_table, y_position)

    due_date = (
        job.delivery_date.strftime("%a, %d %b %Y") if job.delivery_date else "N/A"
    )
    tradeoff_display = dict(SpeedQualityTradeoff.choices).get(
        job.speed_quality_tradeoff, job.speed_quality_tradeoff
    )
    pricing_display = job.get_pricing_methodology_display()
    meta_items = [
        ("DUE", due_date),
        ("ORDER", job.order_number or "N/A"),
        ("PRICING", pricing_display),
        ("APPROVED", _approval_age_display(job)),
        ("SPEED/QUALITY", tradeoff_display),
    ]
    meta_table = Table(
        [
            [
                _plain_paragraph(label, brief_label_style)
                for label, _value in meta_items
            ],
            [
                _plain_paragraph(value, brief_value_style)
                for _label, value in meta_items
            ],
        ],
        colWidths=[CONTENT_WIDTH / len(meta_items)] * len(meta_items),
    )
    meta_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), ROW_ALT),
                ("TEXTCOLOR", (0, 0), (-1, 0), TEXT_MUTED),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    y_position = _draw_table(pdf, meta_table, y_position)

    time_breakdown = get_time_breakdown(job)
    labour_rows = [
        [
            _plain_paragraph("LABOUR BUDGET", brief_label_inverse_style),
            _plain_paragraph("BUDGET", brief_label_inverse_style),
            _plain_paragraph("REMAINING", brief_label_inverse_style),
        ]
    ]
    workshop_row_numbers = []
    for subtype_entry in time_breakdown["subtype_breakdown"]:
        style = (
            brief_value_bold_style
            if subtype_entry["is_workshop"]
            else brief_value_style
        )
        if subtype_entry["is_workshop"]:
            workshop_row_numbers.append(len(labour_rows))
        labour_rows.append(
            [
                _plain_paragraph(subtype_entry["name"], style),
                _plain_paragraph(
                    format_hours_display(subtype_entry["estimated_hours"]),
                    style,
                ),
                _plain_paragraph(
                    _remaining_hours_text(subtype_entry["remaining_hours"]),
                    style,
                ),
            ]
        )

    labour_table = Table(
        labour_rows,
        colWidths=[CONTENT_WIDTH * 0.45, CONTENT_WIDTH * 0.2, CONTENT_WIDTH * 0.35],
    )
    labour_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), PRIMARY),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    y_position = _draw_table(pdf, labour_table, y_position - 8)

    y_position = _draw_spec_section(
        pdf,
        y_position - 8,
        "DESCRIPTION",
        escape(str(job.description or "N/A")),
    )
    return _draw_spec_section(
        pdf,
        y_position,
        "NOTES / WORK INSTRUCTIONS",
        convert_html_to_reportlab(job.notes) if job.notes else "N/A",
    )


def add_delivery_docket_details_table(
    pdf,
    y_position,
    job: Job,
):
    """Render the delivery docket details with page-aware wrapping."""
    company_name = job.company.name if job.company else "N/A"
    contact_name = job.contact.name if job.contact else ""

    contact_phone = _primary_phone_for_job(job)
    contact_info = (
        f"{contact_name}<br/>{contact_phone}" if contact_phone else contact_name
    )

    # Delivery docket details - no workshop time or internal notes
    job_details = [
        [
            Paragraph(company_name, header_company_style),
            Paragraph(contact_info, header_contact_style),
        ],
        [
            Paragraph("DESCRIPTION", label_style),
            Paragraph(job.description or "N/A", body_style),
        ],
        [
            Paragraph("ENTRY DATE", label_style),
            timezone.localtime(
                job.created_at, timezone.get_current_timezone()
            ).strftime("%a, %d %b %Y"),
        ],
        [
            Paragraph("DUE DATE", label_style),
            (
                job.delivery_date.strftime("%a, %d %b %Y")
                if job.delivery_date
                else "N/A"
            ),
        ],
        [
            Paragraph("ORDER NUMBER", label_style),
            Paragraph(job.order_number or "N/A", body_style),
        ],
    ]

    details_table = Table(job_details, colWidths=[180, CONTENT_WIDTH - 180])
    details_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), PRIMARY),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("TOPPADDING", (0, 0), (-1, 0), 10),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 10),
                ("FONTNAME", (0, 1), (0, -1), "Helvetica-Bold"),
                ("TEXTCOLOR", (0, 1), (0, -1), TEXT_MUTED),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ALIGN", (0, 0), (-1, -1), "LEFT"),
                ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 1), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 1), (-1, -1), 6),
            ]
        )
    )

    y_position = draw_table_with_page_breaks(pdf, details_table, y_position)

    if y_position - 36 <= MARGIN:
        return _advance_to_new_page(pdf)

    return y_position - 36


def add_handover_section(pdf, job):
    """Add delivery details and handover fields at the bottom of the page."""
    # Build positions from the bottom of the page upward
    y = MARGIN
    y_notes_3 = y
    y += 20
    y_notes_2 = y
    y += 20
    y_notes_1 = y
    y += 25
    y_date = y
    y += 25
    y_signature = y
    y += 25
    y_name = y
    y += 30
    y_received = y
    y += 30
    y_docket_number = y
    y += 20
    y_delivery_date = y

    # Autogenerated fields
    pdf.setFont("Helvetica-Bold", 10)
    pdf.setFillColor(TEXT_MUTED)
    pdf.drawString(MARGIN, y_delivery_date, "Delivery Date:")
    pdf.setFont("Helvetica", 10)
    pdf.setFillColor(TEXT_DARK)
    delivery_date = timezone.localtime(
        timezone.now(), timezone.get_current_timezone()
    ).strftime("%a, %d %b %Y")
    pdf.drawString(MARGIN + 100, y_delivery_date, delivery_date)

    pdf.setFont("Helvetica-Bold", 10)
    pdf.setFillColor(TEXT_MUTED)
    pdf.drawString(MARGIN, y_docket_number, "Delivery Docket Number:")
    pdf.setFont("Helvetica", 10)
    pdf.setFillColor(TEXT_DARK)
    pdf.drawString(MARGIN + 140, y_docket_number, str(job.job_number))

    # "Received" header
    pdf.setFont("Helvetica-Bold", 12)
    pdf.setFillColor(TEXT_DARK)
    pdf.drawString(MARGIN, y_received, "Received")

    # Manual fill-in fields
    pdf.setFont("Helvetica-Bold", 10)
    pdf.setFillColor(TEXT_MUTED)
    pdf.setStrokeColor(BORDER)

    pdf.drawString(MARGIN, y_name, "Name:")
    pdf.line(MARGIN + 70, y_name, MARGIN + 250, y_name)

    pdf.drawString(MARGIN, y_signature, "Signature:")
    pdf.line(MARGIN + 70, y_signature, MARGIN + 250, y_signature)

    pdf.drawString(MARGIN, y_date, "Date:")
    pdf.line(MARGIN + 70, y_date, MARGIN + 250, y_date)

    pdf.drawString(MARGIN, y_notes_1, "Notes:")
    pdf.line(MARGIN + 70, y_notes_1, PAGE_WIDTH - MARGIN, y_notes_1)
    pdf.line(MARGIN + 70, y_notes_2, PAGE_WIDTH - MARGIN, y_notes_2)
    pdf.line(MARGIN + 70, y_notes_3, PAGE_WIDTH - MARGIN, y_notes_3)


def add_materials_used_table(pdf: canvas.Canvas, y_position: float, job: Job) -> float:
    """Render the materials notes table with actual materials used plus blank rows."""
    materials_data = [["DESCRIPTION", "QUANTITY", "RETAIL PRICE"]]

    # Get actual materials used from latest_actual cost set
    if job.latest_actual:
        material_lines = [
            line
            for line in _cost_lines_for_pdf(job.latest_actual)
            if line.kind == "material"
        ]
        material_lines.sort(key=lambda line: line.quantity, reverse=True)

        for line in material_lines:
            materials_data.append(
                [
                    line.desc or "",
                    f"{line.quantity:.2f}" if line.quantity else "",
                    format_retail_line_total(line),
                ]
            )

    # Always add 5 blank rows for handwritten entries
    for _ in range(5):
        materials_data.append(["", "", ""])

    materials_table = Table(
        materials_data,
        colWidths=[CONTENT_WIDTH * 0.58, CONTENT_WIDTH * 0.17, CONTENT_WIDTH * 0.25],
    )
    materials_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), PRIMARY),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                ("TOPPADDING", (0, 0), (-1, 0), 8),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ROW_ALT]),
                ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 1), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 1), (-1, -1), 10),
            ]
        )
    )

    # Calculate minimum space needed to avoid orphaning the materials section
    # "Materials Used" heading: 14pt font + 25pt spacing = 39pt
    # Header row: 8pt top + 8pt bottom padding + ~12pt text + border = ~29pt
    # Data rows (5): 10pt top + 10pt bottom padding + ~10pt text + border = ~31pt each = 155pt
    # Total: ~223pt minimum to show heading + full table
    min_space_needed = 223
    if y_position - min_space_needed <= MARGIN:
        y_position = _advance_to_new_page(pdf)

    pdf.setFont("Helvetica-Bold", 14)
    pdf.setFillColor(TEXT_DARK)
    pdf.drawString(MARGIN, y_position, "Materials Used")
    y_position -= 25

    y_position = draw_table_with_page_breaks(pdf, materials_table, y_position)

    if y_position - 20 <= MARGIN:
        return _advance_to_new_page(pdf)

    return y_position - 20


def create_image_document(image_files: list[JobFile]) -> BytesIO:
    """Create a PDF containing the selected images, one per page."""
    image_buffer = BytesIO()
    if not image_files:
        return image_buffer

    pdf = canvas.Canvas(image_buffer, pagesize=A4)

    for i, job_file in enumerate(image_files):
        file_path = os.path.join(settings.DROPBOX_WORKFLOW_FOLDER, job_file.file_path)
        if not os.path.exists(file_path):
            continue

        try:
            width, height = _fit_dimensions(
                file_path, CONTENT_WIDTH, PAGE_HEIGHT - 2 * MARGIN - 50
            )
            x = MARGIN + (CONTENT_WIDTH - width) / 2
            y_position = PAGE_HEIGHT - MARGIN - 10
            pdf.drawImage(file_path, x, y_position - height, width=width, height=height)

            pdf.setFont("Helvetica-Oblique", 9)
            pdf.drawString(MARGIN, 30, f"File: {job_file.filename}")

            if i < len(image_files) - 1:
                pdf.showPage()
        except Exception as e:
            logger.error(f"Failed to add image {job_file.filename}: {e}")
            pdf.setFont("Helvetica", 12)
            pdf.drawString(
                MARGIN, PAGE_HEIGHT - MARGIN - 50, f"Error adding image: {str(e)}"
            )
            if i < len(image_files) - 1:
                pdf.showPage()

    pdf.save()
    image_buffer.seek(0)
    return image_buffer


def process_attachments(
    main_buffer: BytesIO, image_files: list[JobFile], pdf_files: list[JobFile]
) -> BytesIO:
    """Append images and/or external PDFs to the main document."""
    if not image_files and not pdf_files:
        return main_buffer

    if not image_files and pdf_files:
        return merge_pdfs([main_buffer] + get_pdf_file_paths(pdf_files))

    image_buffer = create_image_document(image_files)
    if not pdf_files:
        return merge_pdfs([main_buffer, image_buffer])

    return merge_pdfs([main_buffer, image_buffer] + get_pdf_file_paths(pdf_files))


def get_pdf_file_paths(pdf_files: list[JobFile]) -> list[str]:
    """Resolve absolute paths for PDF attachments on disk."""
    file_paths: list[str] = []
    for job_file in pdf_files:
        file_path = os.path.join(settings.DROPBOX_WORKFLOW_FOLDER, job_file.file_path)
        if os.path.exists(file_path):
            file_paths.append(file_path)
    return file_paths


def merge_pdfs(pdf_sources: list[Union[BytesIO, str]]) -> BytesIO:
    """
    Merge multiple PDFs (BytesIO or file paths) into a single buffer.
    """
    merger = PdfWriter()
    buffers_to_close: list[BytesIO] = []

    try:
        for source in pdf_sources:
            try:
                if isinstance(source, BytesIO):
                    merger.append(source)
                    buffers_to_close.append(source)
                else:
                    merger.append(source)
            except Exception as e:
                logger.error(f"Failed to merge PDF: {e}")

        result_buffer = BytesIO()
        merger.write(result_buffer)
        result_buffer.seek(0)
        return result_buffer
    finally:
        for buffer in buffers_to_close:
            try:
                buffer.close()
            except Exception as e:
                logger.error(f"Error closing buffer: {str(e)}")
                try:
                    persist_and_raise(e)
                except AlreadyLoggedException:
                    pass
