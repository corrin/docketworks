"""Purchase-order PDF generation with ReportLab.

Layout is unchanged: wide-logo letterhead, PO header block, supplier block,
then an item-code/description/quantity table that reflows onto a second page
when it does not fit.
"""

import logging
from io import BytesIO

from PIL import Image, ImageFile
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, Table, TableStyle

from apps.core.models import CompanyDefaults
from apps.purchasing.models import PurchaseOrder

logger = logging.getLogger(__name__)

PAGE_WIDTH, PAGE_HEIGHT = A4
MARGIN = 50
CONTENT_WIDTH = PAGE_WIDTH - (2 * MARGIN)

_styles = getSampleStyleSheet()
NORMAL_STYLE = _styles["Normal"]
ImageFile.LOAD_TRUNCATED_IMAGES = True

PRIMARY_COLOR = colors.HexColor("#000080")  # Navy blue


class PurchaseOrderPDFGenerator:
    """Draws one purchase order onto an in-memory PDF canvas."""

    def __init__(self, purchase_order: PurchaseOrder) -> None:
        """Bind the PO and open a fresh A4 canvas over a BytesIO buffer."""
        self.purchase_order = purchase_order
        self.buffer = BytesIO()
        self.pdf = canvas.Canvas(self.buffer, pagesize=A4)

    def generate(self) -> BytesIO:
        """Render the document and return the rewound buffer."""
        y_position = self.add_logo()
        y_position = self.add_header_info(y_position)
        y_position = self.add_supplier_info(y_position)
        self.add_line_items_table(y_position)
        self.pdf.save()
        self.buffer.seek(0)
        return self.buffer

    def add_logo(self) -> float:
        """Draw the wide logo across the content width as a letterhead."""
        company = CompanyDefaults.get_solo()
        if not company.logo_wide:
            raise ValueError("No wide logo uploaded in Company Defaults")
        with Image.open(company.logo_wide.path) as img:
            src_w, src_h = img.size
        img_height_pt = src_h * (CONTENT_WIDTH / src_w)
        banner_top = PAGE_HEIGHT - MARGIN
        self.pdf.drawImage(
            ImageReader(company.logo_wide.path),
            MARGIN,
            banner_top - img_height_pt,
            width=CONTENT_WIDTH,
            height=img_height_pt,
            mask="auto",
        )
        return banner_top - img_height_pt - 20

    def _labelled(self, y_position: float, label: str, value: str, offset: int) -> float:
        self.pdf.setFont("Helvetica-Bold", 12)
        self.pdf.drawString(MARGIN, y_position, label)
        self.pdf.setFont("Helvetica", 12)
        self.pdf.drawString(MARGIN + offset, y_position, value)
        return y_position - 20

    def add_header_info(self, y_position: float) -> float:
        """Add the PURCHASE ORDER title and the PO's header fields."""
        po = self.purchase_order
        self.pdf.setFont("Helvetica-Bold", 18)
        self.pdf.setFillColor(PRIMARY_COLOR)
        self.pdf.drawString(MARGIN, y_position, "PURCHASE ORDER")
        y_position -= 30
        self.pdf.setFillColor(colors.black)

        self.pdf.setFont("Helvetica-Bold", 12)
        self.pdf.drawString(MARGIN, y_position, "PO Number:")
        self.pdf.setFont("Helvetica", 12)
        self.pdf.drawString(MARGIN + 80, y_position, po.po_number)

        self.pdf.setFont("Helvetica-Bold", 12)
        self.pdf.drawString(PAGE_WIDTH - MARGIN - 120, y_position, "Order Date:")
        self.pdf.setFont("Helvetica", 12)
        order_date = po.order_date.strftime("%d/%m/%Y") if po.order_date else "N/A"
        self.pdf.drawString(PAGE_WIDTH - MARGIN - 50, y_position, order_date)
        y_position -= 20

        if po.expected_delivery:
            y_position = self._labelled(
                y_position,
                "Expected Delivery:",
                po.expected_delivery.strftime("%d/%m/%Y"),
                120,
            )
        if po.reference:
            y_position = self._labelled(y_position, "Reference:", po.reference, 80)
        return y_position - 10

    def add_supplier_info(self, y_position: float) -> float:
        """Add the supplier block and pickup address, when present."""
        supplier = self.purchase_order.supplier
        if not supplier:
            return y_position

        self.pdf.setFont("Helvetica-Bold", 14)
        self.pdf.setFillColor(PRIMARY_COLOR)
        self.pdf.drawString(MARGIN, y_position, "Supplier Information")
        self.pdf.setFillColor(colors.black)
        y_position -= 25

        y_position = self._labelled(y_position, "Name:", supplier.name, 50)
        if supplier.email:
            y_position = self._labelled(y_position, "Email:", supplier.email, 50)
        supplier_phone = supplier.primary_phone_value()
        if supplier_phone:
            y_position = self._labelled(y_position, "Phone:", supplier_phone, 50)

        pickup_address = self.purchase_order.pickup_address
        if pickup_address:
            y_position -= 5
            self.pdf.setFont("Helvetica-Bold", 12)
            self.pdf.drawString(MARGIN, y_position, "Pickup Address:")
            y_position -= 15
            self.pdf.setFont("Helvetica", 11)
            self.pdf.drawString(MARGIN + 10, y_position, pickup_address.name)
            y_position -= 15
            self.pdf.drawString(MARGIN + 10, y_position, pickup_address.formatted_address)
            y_position -= 15
            if pickup_address.notes:
                self.pdf.setFont("Helvetica-Oblique", 10)
                self.pdf.drawString(MARGIN + 10, y_position, f"Note: {pickup_address.notes}")
                y_position -= 15
        return y_position - 10

    def add_line_items_table(self, y_position: float) -> float:
        """Add the order-items table, breaking to a new page when needed."""
        self.pdf.setFont("Helvetica-Bold", 14)
        self.pdf.setFillColor(PRIMARY_COLOR)
        self.pdf.drawString(MARGIN, y_position, "Order Items")
        self.pdf.setFillColor(colors.black)
        y_position -= 25

        line_items = list(self.purchase_order.po_lines.all())
        if not line_items:
            self.pdf.setFont("Helvetica", 12)
            self.pdf.drawString(MARGIN, y_position, "No items in this purchase order.")
            return y_position - 20

        table_data: list[list[object]] = [["Item Code", "Description", "Qty"]]
        for item in line_items:
            table_data.append(
                [
                    Paragraph(item.item_code or "", NORMAL_STYLE),
                    Paragraph(item.description or "", NORMAL_STYLE),
                    f"{float(item.quantity):.2f}" if item.quantity else "0.00",
                ]
            )

        lines_table = Table(
            table_data,
            colWidths=[CONTENT_WIDTH * 0.25, CONTENT_WIDTH * 0.65, CONTENT_WIDTH * 0.1],
        )
        lines_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), PRIMARY_COLOR),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, 0), 9),
                    ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                    ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                    ("FONTSIZE", (0, 1), (-1, -1), 8),
                    ("ALIGN", (-1, 1), (-1, -1), "RIGHT"),
                    ("ALIGN", (0, 1), (-2, -1), "LEFT"),
                    ("VALIGN", (0, 1), (-1, -1), "TOP"),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ("LEFTPADDING", (0, 0), (-1, -1), 3),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ]
            )
        )

        _table_width, table_height = lines_table.wrap(CONTENT_WIDTH, PAGE_HEIGHT)
        if y_position - table_height < MARGIN + 50:  # 50pt reserved for the footer
            self.pdf.showPage()
            y_position = PAGE_HEIGHT - MARGIN
            self.pdf.setFont("Helvetica-Bold", 14)
            self.pdf.drawString(MARGIN, y_position, "Order Items (Continued)")
            y_position -= 25

        lines_table.drawOn(self.pdf, MARGIN, y_position - table_height)
        return y_position - table_height - 20


def create_purchase_order_pdf(purchase_order: PurchaseOrder) -> BytesIO:
    """Generate the PDF for ``purchase_order`` and return its buffer."""
    return PurchaseOrderPDFGenerator(purchase_order).generate()
