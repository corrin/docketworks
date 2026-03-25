import logging
import os
import re
import time
from collections import defaultdict
from io import BytesIO
from typing import Callable, Optional

from bs4 import BeautifulSoup, NavigableString
from django.conf import settings
from django.utils import timezone
from PIL import Image, ImageFile
from PyPDF2 import PdfWriter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, Table, TableStyle

from apps.job.enums import SpeedQualityTradeoff
from apps.job.models import Job
from apps.workflow.exceptions import AlreadyLoggedException
from apps.workflow.models import CompanyDefaults
from apps.workflow.services.error_persistence import persist_and_raise

logger = logging.getLogger(__name__)


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


def get_workshop_hours(job: Job) -> float:
    """
    Calculate workshop time allocated from the latest estimate or quote.

    Sums all time CostLines except those ending in "office time" (case-insensitive).
    Falls back to quote if estimate has zero workshop hours.
    """
    estimate = job.cost_sets.filter(kind="estimate").order_by("-rev").first()
    if not estimate:
        exc = ValueError(f"Job {job.job_number} has no estimate CostSet")
        raise exc

    lines = estimate.cost_lines.filter(kind="time").exclude(
        desc__iendswith=" office time"
    )
    workshop_hours = sum(float(line.quantity) for line in lines)

    if workshop_hours <= 0:
        quote = job.cost_sets.filter(kind="quote").order_by("-rev").first()
        if not quote:
            exc = ValueError(
                f"Job {job.job_number} has no quote CostSet to fall back to"
            )
            raise exc

        lines = quote.cost_lines.filter(kind="time").exclude(
            desc__iendswith=" office time"
        )
        workshop_hours = sum(float(line.quantity) for line in lines)

    return workshop_hours


def get_time_breakdown(job: Job) -> dict:
    """
    Get detailed time breakdown for workshop PDF.

    Returns:
        dict with keys:
            - budgeted_hours: Total hours from estimate/quote (uses existing logic)
            - used_hours: Total hours from latest_actual
            - remaining_hours: Difference
            - is_over_budget: True if over budget
            - staff_breakdown: List of dicts with staff name and hours worked
    """
    budgeted_hours = get_workshop_hours(job)
    used_hours = 0.0
    staff_breakdown = []

    # Get used hours and staff breakdown from actual
    if job.latest_actual:
        if job.latest_actual.summary:
            used_hours = float(job.latest_actual.summary.get("hours", 0.0))

        # Get breakdown by staff member
        time_lines = (
            job.latest_actual.cost_lines.filter(kind="time")
            .exclude(desc__iendswith=" office time")
            .select_related("cost_set")
        )

        # Group by staff
        staff_hours = defaultdict(float)
        for line in time_lines:
            staff_id = line.meta.get("staff_id")
            if not staff_id:
                exc = ValueError(
                    f"CostLine {line.id} for job {job.job_number} has no staff_id in meta"
                )
                raise exc

            # Trust the data - staff must exist
            from apps.accounts.models import Staff

            staff = Staff.objects.get(id=staff_id)
            staff_name = f"{staff.first_name} {staff.last_name}"
            staff_hours[staff_name] += float(line.quantity)

        # Convert to list of dicts sorted by hours descending
        staff_breakdown = [
            {"name": name, "hours": hours}
            for name, hours in sorted(
                staff_hours.items(), key=lambda x: x[1], reverse=True
            )
        ]

    remaining_hours = budgeted_hours - used_hours
    is_over_budget = used_hours > budgeted_hours and budgeted_hours > 0

    return {
        "budgeted_hours": budgeted_hours,
        "used_hours": used_hours,
        "remaining_hours": remaining_hours,
        "is_over_budget": is_over_budget,
        "staff_breakdown": staff_breakdown,
    }


# Page metrics (A4: 210 x 297 mm)
PAGE_WIDTH, PAGE_HEIGHT = A4
MARGIN = 50
CONTENT_WIDTH = PAGE_WIDTH - (2 * MARGIN)

styles = getSampleStyleSheet()

# Palette and typography
PRIMARY = colors.HexColor("#004AAD")
TEXT_DARK = colors.HexColor("#0F172A")
TEXT_MUTED = colors.HexColor("#334155")
BORDER = colors.HexColor("#CBD5E1")
ROW_ALT = colors.HexColor("#F8FAFC")

# Paragraph styles for table content
header_client_style = ParagraphStyle(
    "HeaderClient",
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


def get_image_dimensions(image_path):
    """Return image dimensions in points, scaled to fit CONTENT_WIDTH."""
    wait_until_file_ready(image_path)
    with Image.open(image_path) as img:
        img_width, img_height = img.size
        img_width_pt, img_height_pt = img_width, img_height
        if img_width_pt > CONTENT_WIDTH:
            scale = CONTENT_WIDTH / img_width_pt
            img_width_pt = CONTENT_WIDTH
            img_height_pt *= scale
        return img_width_pt, img_height_pt


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


def create_workshop_pdf(job):
    """
    Generate the workshop PDF with materials table and attachments.
    """
    try:
        main_buffer = create_workshop_main_document(job)

        files_to_print = job.files.filter(print_on_jobsheet=True)
        if not files_to_print.exists():
            return main_buffer

        image_files = [f for f in files_to_print if f.mime_type.startswith("image/")]
        pdf_files = [f for f in files_to_print if f.mime_type == "application/pdf"]

        return process_attachments(main_buffer, image_files, pdf_files)
    except Exception as e:
        logger.error(f"Error creating workshop PDF: {str(e)}")
        raise e


def create_delivery_docket_pdf(job):
    """
    Generate a delivery docket PDF (no materials, workshop time, or internal notes).
    Includes handover section with signature, date, and notes fields.
    Does not include job attachments - delivery dockets are kept minimal.
    """
    try:
        return create_delivery_docket_main_document(job)
    except Exception as e:
        logger.error(f"Error creating delivery docket PDF: {str(e)}")
        raise e


def create_workshop_main_document(job):
    """Create the workshop cover document with header, details, time used, and materials tables."""
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)

    y_position = PAGE_HEIGHT - MARGIN
    y_position = add_logo(pdf, y_position)
    y_position = add_title(pdf, y_position, job)
    y_position = add_workshop_details_table(pdf, y_position, job)
    y_position = add_time_used_table(pdf, y_position, job)
    y_position = add_materials_used_table(pdf, y_position, job)

    pdf.save()
    buffer.seek(0)
    return buffer


def create_delivery_docket_main_document(job):
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
    y_position = add_logo(pdf, y_position)
    y_position = add_title(
        pdf, y_position, job, title_prefix=f"DELIVERY DOCKET - {copy_label}"
    )
    y_position = add_delivery_docket_details_table(pdf, y_position, job)
    if y_position <= MARGIN + 245:
        _advance_to_new_page(pdf)
    add_handover_section(pdf, job)

    # Start new page for Customer Copy
    pdf.showPage()

    # Second page - Customer Copy
    y_position = PAGE_HEIGHT - MARGIN
    y_position = add_logo(pdf, y_position)
    y_position = add_title(
        pdf, y_position, job, title_prefix="DELIVERY DOCKET - Customer Copy"
    )
    y_position = add_delivery_docket_details_table(pdf, y_position, job)
    if y_position <= MARGIN + 245:
        _advance_to_new_page(pdf)
    add_handover_section(pdf, job)

    pdf.save()
    buffer.seek(0)
    return buffer


def add_logo(pdf, y_position):
    """Draw the logo centred at the top and return the updated y position."""
    logo_path = os.path.join(settings.BASE_DIR, "static", "logo_msm.png")
    if not os.path.exists(logo_path):
        return y_position
    logo = ImageReader(logo_path)
    x = MARGIN + (CONTENT_WIDTH - 150) / 2
    pdf.drawImage(logo, x, y_position - 150, width=150, height=150, mask="auto")
    return y_position - 200


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


def add_title(pdf, y_position, job, title_prefix=None):
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


def add_time_used_table(pdf, y_position, job: Job):
    """
    Render the time used table showing staff members and hours worked,
    similar to the materials notes table.

    Returns the updated y_position after drawing the table.
    """
    time_breakdown = get_time_breakdown(job)

    # Build table data - header row + actual time entries + 5 blank rows
    time_data = [["STAFF MEMBER", "HOURS", "REMAINING"]]

    # Calculate running remaining hours
    budgeted = time_breakdown["budgeted_hours"]
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


def add_workshop_details_table(pdf, y_position, job: Job):
    """Render the workshop job details with workshop time and internal notes."""
    client_name = job.client.name if job.client else "N/A"
    contact_name = job.contact.name if job.contact else ""

    contact_phone = (
        (job.contact.phone if job.contact and job.contact.phone else None)
        or (job.client.phone if job.client else None)
        or ""
    )
    contact_info = (
        f"{contact_name}<br/>{contact_phone}" if contact_phone else contact_name
    )

    # Get time summary for the one-line display
    time_breakdown = get_time_breakdown(job)
    remaining = time_breakdown["remaining_hours"]
    total = time_breakdown["budgeted_hours"]

    if time_breakdown["is_over_budget"]:
        workshop_display = (
            f"{format_hours_display(abs(remaining))} OVER BUDGET"
            f" ({format_hours_display(total)} total)"
        )
    else:
        workshop_display = (
            f"{format_hours_display(remaining)} remaining"
            f" ({format_hours_display(total)} total)"
        )

    pricing_suffix = (
        " (T&M)" if job.pricing_methodology == "time_materials" else " (Quoted)"
    )
    workshop_display += pricing_suffix

    # Get speed/quality tradeoff display
    tradeoff_display = dict(SpeedQualityTradeoff.choices).get(
        job.speed_quality_tradeoff, job.speed_quality_tradeoff
    )

    # Use Paragraph styles so header text is white over the blue background
    job_details = [
        [
            Paragraph(client_name, header_client_style),
            Paragraph(contact_info, header_contact_style),
        ],
        [
            Paragraph("DESCRIPTION", label_style),
            Paragraph(job.description or "N/A", body_style),
        ],
        [
            Paragraph("WORKSHOP TIME", label_style),
            Paragraph(workshop_display, body_style),
        ],
        [
            Paragraph("SPEED/QUALITY", label_style),
            Paragraph(tradeoff_display, body_style),
        ],
        [
            Paragraph("NOTES", label_style),
            Paragraph(
                convert_html_to_reportlab(job.notes) if job.notes else "N/A", body_style
            ),
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
                job.delivery_date.strftime(
                    "%a, %d %b %Y"
                )  # Defined by the user + date object, doesn't need TZ conversion.
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


def add_delivery_docket_details_table(
    pdf,
    y_position,
    job: Job,
):
    """Render the delivery docket details with page-aware wrapping."""
    client_name = job.client.name if job.client else "N/A"
    contact_name = job.contact.name if job.contact else ""

    contact_phone = (
        (job.contact.phone if job.contact and job.contact.phone else None)
        or (job.client.phone if job.client else None)
        or ""
    )
    contact_info = (
        f"{contact_name}<br/>{contact_phone}" if contact_phone else contact_name
    )

    # Delivery docket details - no workshop time or internal notes
    job_details = [
        [
            Paragraph(client_name, header_client_style),
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
    # Position at bottom of page with margin
    y_position = MARGIN + 205

    # Autogenerated fields first
    pdf.setFont("Helvetica-Bold", 10)
    pdf.setFillColor(TEXT_MUTED)
    pdf.drawString(MARGIN, y_position, "Delivery Date:")
    pdf.setFont("Helvetica", 10)
    pdf.setFillColor(TEXT_DARK)
    delivery_date = timezone.localtime(
        timezone.now(), timezone.get_current_timezone()
    ).strftime("%a, %d %b %Y")
    pdf.drawString(MARGIN + 100, y_position, delivery_date)
    y_position -= 20

    pdf.setFont("Helvetica-Bold", 10)
    pdf.setFillColor(TEXT_MUTED)
    pdf.drawString(MARGIN, y_position, "Delivery Docket Number:")
    pdf.setFont("Helvetica", 10)
    pdf.setFillColor(TEXT_DARK)
    pdf.drawString(MARGIN + 140, y_position, str(job.job_number))
    y_position -= 30

    # "Received" header
    pdf.setFont("Helvetica-Bold", 12)
    pdf.setFillColor(TEXT_DARK)
    pdf.drawString(MARGIN, y_position, "Received")
    y_position -= 30

    # Manual fill-in fields
    pdf.setFont("Helvetica-Bold", 10)
    pdf.setFillColor(TEXT_MUTED)
    pdf.drawString(MARGIN, y_position, "Name:")
    pdf.setStrokeColor(BORDER)
    pdf.line(MARGIN + 70, y_position, MARGIN + 250, y_position)
    y_position -= 25

    pdf.drawString(MARGIN, y_position, "Signature:")
    pdf.line(MARGIN + 70, y_position, MARGIN + 250, y_position)
    y_position -= 25

    pdf.drawString(MARGIN, y_position, "Date:")
    pdf.line(MARGIN + 70, y_position, MARGIN + 250, y_position)
    y_position -= 25

    pdf.drawString(MARGIN, y_position, "Notes:")
    pdf.line(MARGIN + 70, y_position, PAGE_WIDTH - MARGIN, y_position)
    y_position -= 20
    pdf.line(MARGIN + 70, y_position, PAGE_WIDTH - MARGIN, y_position)
    y_position -= 20
    pdf.line(MARGIN + 70, y_position, PAGE_WIDTH - MARGIN, y_position)


def add_materials_used_table(pdf, y_position, job: Job):
    """Render the materials notes table with actual materials used plus blank rows."""
    materials_data = [["DESCRIPTION", "QUANTITY"]]

    # Get actual materials used from latest_actual cost set
    if job.latest_actual:
        material_lines = job.latest_actual.cost_lines.filter(kind="material").order_by(
            "-quantity"
        )  # Show largest quantities first

        for line in material_lines:
            materials_data.append(
                [
                    line.desc or "",
                    f"{line.quantity:.2f}" if line.quantity else "",
                ]
            )

    # Always add 5 blank rows for handwritten entries
    for _ in range(5):
        materials_data.append(["", ""])

    materials_table = Table(
        materials_data,
        colWidths=[CONTENT_WIDTH * 0.7, CONTENT_WIDTH * 0.3],
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


def create_image_document(image_files):
    """Create a PDF containing the selected images, one per page."""
    if not image_files:
        return None

    image_buffer = BytesIO()
    pdf = canvas.Canvas(image_buffer, pagesize=A4)

    for i, job_file in enumerate(image_files):
        file_path = os.path.join(settings.DROPBOX_WORKFLOW_FOLDER, job_file.file_path)
        if not os.path.exists(file_path):
            continue

        try:
            width, height = get_image_dimensions(file_path)
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


def process_attachments(main_buffer, image_files, pdf_files):
    """Append images and/or external PDFs to the main document."""
    if not image_files and not pdf_files:
        return main_buffer

    if not image_files and pdf_files:
        return merge_pdfs([main_buffer] + get_pdf_file_paths(pdf_files))

    image_buffer = create_image_document(image_files)
    if not pdf_files:
        return merge_pdfs([main_buffer, image_buffer])

    return merge_pdfs([main_buffer, image_buffer] + get_pdf_file_paths(pdf_files))


def get_pdf_file_paths(pdf_files):
    """Resolve absolute paths for PDF attachments on disk."""
    file_paths = []
    for job_file in pdf_files:
        file_path = os.path.join(settings.DROPBOX_WORKFLOW_FOLDER, job_file.file_path)
        if os.path.exists(file_path):
            file_paths.append(file_path)
    return file_paths


def merge_pdfs(pdf_sources):
    """
    Merge multiple PDFs (BytesIO or file paths) into a single buffer.
    """
    merger = PdfWriter()
    buffers_to_close = []

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
