import logging
from io import BytesIO

from PIL import Image, ImageFile
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, Table, TableStyle

from apps.workflow.models.company_defaults import CompanyDefaults

logger = logging.getLogger(__name__)

# A4 page dimensions
PAGE_WIDTH, PAGE_HEIGHT = A4
MARGIN = 50
CONTENT_WIDTH = PAGE_WIDTH - (2 * MARGIN)

# Initialize styles
styles = getSampleStyleSheet()
normal_style = styles["Normal"]
bold_style = styles["Heading4"]
ImageFile.LOAD_TRUNCATED_IMAGES = True

# Primary color for headers
PRIMARY_COLOR = colors.HexColor("#000080")  # Navy blue


class PurchaseOrderPDFGenerator:
    """
    Generator class for Purchase Order PDF documents.
    """

    def __init__(self, purchase_order):
        """
        Initialize the PDF generator with a purchase order.

        Args:
            purchase_order: The PurchaseOrder model instance to generate PDF for
        """
        self.purchase_order = purchase_order
        self.buffer = BytesIO()
        self.pdf = canvas.Canvas(self.buffer, pagesize=A4)
        self.y_position = PAGE_HEIGHT - MARGIN

    def generate(self):
        """
        Generate the complete PDF document.
        Returns:
            BytesIO: Buffer containing the generated PDF
        """
        try:
            # Add content to PDF
            self.y_position = self.add_logo(self.y_position)
            self.y_position = self.add_header_info(self.y_position)
            self.y_position = self.add_supplier_info(self.y_position)
            self.y_position = self.add_line_items_table(self.y_position)

            # Save PDF and return buffer
            self.pdf.save()
            self.buffer.seek(0)
            return self.buffer

        except Exception as e:
            logger.exception(
                f"Error generating PDF for PO {self.purchase_order.id}: {str(e)}"
            )
            raise

    def add_logo(self, y_position):
        """Draw the wide logo across the content width as a letterhead."""
        company = CompanyDefaults.get_solo()
        if not company.logo_wide:
            raise ValueError("No wide logo uploaded in Company Defaults")
        with Image.open(company.logo_wide.path) as img:
            src_w, src_h = img.size
        img_width_pt = CONTENT_WIDTH
        img_height_pt = src_h * (CONTENT_WIDTH / src_w)
        banner = ImageReader(company.logo_wide.path)
        banner_top = PAGE_HEIGHT - MARGIN
        self.pdf.drawImage(
            banner,
            MARGIN,
            banner_top - img_height_pt,
            width=img_width_pt,
            height=img_height_pt,
            mask="auto",
        )
        return banner_top - img_height_pt - 20

    def add_header_info(self, y_position):
        """Add purchase order header and details to the PDF."""
        # Main title
        self.pdf.setFont("Helvetica-Bold", 18)
        self.pdf.setFillColor(PRIMARY_COLOR)
        self.pdf.drawString(MARGIN, y_position, "PURCHASE ORDER")
        y_position -= 30

        # Reset color for rest of content
        self.pdf.setFillColor(colors.black)

        # PO Number and Date - in two columns
        self.pdf.setFont("Helvetica-Bold", 12)
        self.pdf.drawString(MARGIN, y_position, "PO Number:")
        self.pdf.setFont("Helvetica", 12)
        self.pdf.drawString(MARGIN + 80, y_position, str(self.purchase_order.po_number))

        # Order date on the right
        self.pdf.setFont("Helvetica-Bold", 12)
        self.pdf.drawString(PAGE_WIDTH - MARGIN - 120, y_position, "Order Date:")
        self.pdf.setFont("Helvetica", 12)
        order_date = (
            self.purchase_order.order_date.strftime("%d/%m/%Y")
            if self.purchase_order.order_date
            else "N/A"
        )
        self.pdf.drawString(PAGE_WIDTH - MARGIN - 50, y_position, order_date)
        y_position -= 20

        # Expected delivery
        if self.purchase_order.expected_delivery:
            self.pdf.setFont("Helvetica-Bold", 12)
            self.pdf.drawString(MARGIN, y_position, "Expected Delivery:")
            self.pdf.setFont("Helvetica", 12)
            delivery_date = self.purchase_order.expected_delivery.strftime("%d/%m/%Y")
            self.pdf.drawString(MARGIN + 120, y_position, delivery_date)
            y_position -= 20

        # Reference if available
        if self.purchase_order.reference:
            self.pdf.setFont("Helvetica-Bold", 12)
            self.pdf.drawString(MARGIN, y_position, "Reference:")
            self.pdf.setFont("Helvetica", 12)
            self.pdf.drawString(
                MARGIN + 80, y_position, str(self.purchase_order.reference)
            )
            y_position -= 20

        return y_position - 10

    def add_supplier_info(self, y_position):
        """Add supplier information section to the PDF."""
        if not self.purchase_order.supplier:
            return y_position

        # Supplier section header
        self.pdf.setFont("Helvetica-Bold", 14)
        self.pdf.setFillColor(PRIMARY_COLOR)
        self.pdf.drawString(MARGIN, y_position, "Supplier Information")
        self.pdf.setFillColor(colors.black)
        y_position -= 25

        supplier = self.purchase_order.supplier

        # Supplier name
        self.pdf.setFont("Helvetica-Bold", 12)
        self.pdf.drawString(MARGIN, y_position, "Name:")
        self.pdf.setFont("Helvetica", 12)
        self.pdf.drawString(MARGIN + 50, y_position, supplier.name)
        y_position -= 20

        # Supplier email
        if supplier.email:
            self.pdf.setFont("Helvetica-Bold", 12)
            self.pdf.drawString(MARGIN, y_position, "Email:")
            self.pdf.setFont("Helvetica", 12)
            self.pdf.drawString(MARGIN + 50, y_position, supplier.email)
            y_position -= 20

        # Supplier phone
        if supplier.phone:
            self.pdf.setFont("Helvetica-Bold", 12)
            self.pdf.drawString(MARGIN, y_position, "Phone:")
            self.pdf.setFont("Helvetica", 12)
            self.pdf.drawString(MARGIN + 50, y_position, supplier.phone)
            y_position -= 20

        # Pickup/Delivery address
        pickup_address = self.purchase_order.pickup_address
        if pickup_address:
            y_position -= 5  # Extra spacing before pickup address
            self.pdf.setFont("Helvetica-Bold", 12)
            self.pdf.drawString(MARGIN, y_position, "Pickup Address:")
            y_position -= 15
            self.pdf.setFont("Helvetica", 11)
            self.pdf.drawString(MARGIN + 10, y_position, pickup_address.name)
            y_position -= 15
            self.pdf.drawString(
                MARGIN + 10, y_position, pickup_address.formatted_address
            )
            y_position -= 15
            if pickup_address.notes:
                self.pdf.setFont("Helvetica-Oblique", 10)
                self.pdf.drawString(
                    MARGIN + 10, y_position, f"Note: {pickup_address.notes}"
                )
                y_position -= 15

        return y_position - 10

    def add_line_items_table(self, y_position):
        """Add the table of purchase order line items."""
        # Table header
        self.pdf.setFont("Helvetica-Bold", 14)
        self.pdf.setFillColor(PRIMARY_COLOR)
        self.pdf.drawString(MARGIN, y_position, "Order Items")
        self.pdf.setFillColor(colors.black)
        y_position -= 25

        # Get line items
        line_items = self.purchase_order.po_lines.all()

        if not line_items.exists():
            self.pdf.setFont("Helvetica", 12)
            self.pdf.drawString(MARGIN, y_position, "No items in this purchase order.")
            return y_position - 20

        # Prepare table headers
        table_data = [
            ["Item Code", "Description", "Qty"],
        ]
        col_widths = [
            CONTENT_WIDTH * 0.25,  # Item Code
            CONTENT_WIDTH * 0.65,  # Description
            CONTENT_WIDTH * 0.1,  # Qty
        ]

        for item in line_items:
            # Use full text without truncation - Paragraph objects will wrap
            description = str(item.description or "")
            item_code = str(item.item_code or "")

            table_data.append(
                [
                    Paragraph(item_code, normal_style),
                    Paragraph(description, normal_style),
                    f"{float(item.quantity):.2f}" if item.quantity else "0.00",
                ]
            )

        # Create table with dynamic column widths
        lines_table = Table(table_data, colWidths=col_widths)

        # Style the table
        table_style = TableStyle(
            [
                # Header styling
                ("BACKGROUND", (0, 0), (-1, 0), PRIMARY_COLOR),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 9),
                ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                # Data rows
                ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 1), (-1, -1), 8),
                ("ALIGN", (-1, 1), (-1, -1), "RIGHT"),  # Right align quantity column
                ("ALIGN", (0, 1), (-2, -1), "LEFT"),  # Left align text columns
                ("VALIGN", (0, 1), (-1, -1), "TOP"),  # Top align for multi-line content
                # Borders
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                # Padding
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ]
        )
        lines_table.setStyle(table_style)

        # Check if table fits on current page
        table_width, table_height = lines_table.wrap(CONTENT_WIDTH, PAGE_HEIGHT)
        if y_position - table_height < MARGIN + 50:  # 50 is space for footer
            # Start new page if needed
            self.pdf.showPage()
            y_position = PAGE_HEIGHT - MARGIN
            # Redraw title on new page
            self.pdf.setFont("Helvetica-Bold", 14)
            self.pdf.drawString(MARGIN, y_position, "Order Items (Continued)")
            y_position -= 25

        lines_table.drawOn(self.pdf, MARGIN, y_position - table_height)
        return y_position - table_height - 20


def create_purchase_order_pdf(purchase_order):
    """
    Factory function to generate a PDF for a purchase order.

    Args:
        purchase_order: The PurchaseOrder instance

    Returns:
        BytesIO: Buffer containing the generated PDF
    """
    generator = PurchaseOrderPDFGenerator(purchase_order)
    return generator.generate()
