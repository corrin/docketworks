"""The PDF Xero renders for a quote, rendered here instead.

Only the quote-PDF inspection reads it, and what it reads is the text layer:
the quote's number and its Terms verbatim. This is the one route where the
fake is weaker than Xero — the application's terms reaching the wire is
proven, Xero's rendering of them is not — and ADR 0060 says so.
"""

from io import BytesIO

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from apps.xero.fake.wire import Json


def render_quote_pdf(quote: dict[str, Json]) -> bytes:
    """Render a one-page PDF carrying the quote's number, contact, lines and terms."""
    buffer = BytesIO()
    page = canvas.Canvas(buffer, pagesize=A4)
    _width, height = A4
    y = height - 72
    page.setFont("Helvetica-Bold", 16)
    page.drawString(72, y, f"Quote {quote.get('QuoteNumber', '')}")
    y -= 28
    page.setFont("Helvetica", 11)
    contact = quote.get("Contact")
    if isinstance(contact, dict):
        page.drawString(72, y, str(contact.get("Name", "")))
        y -= 20
    lines = quote.get("LineItems")
    if isinstance(lines, list):
        for line in lines:
            if not isinstance(line, dict):
                continue
            page.drawString(72, y, f"{line.get('Description', '')}  {line.get('LineAmount', '')}")
            y -= 16
    y -= 12
    page.drawString(72, y, f"Total {quote.get('Total', '')}")
    y -= 28
    terms = quote.get("Terms")
    if isinstance(terms, str) and terms:
        for paragraph in terms.splitlines() or [terms]:
            page.drawString(72, y, paragraph)
            y -= 14
    page.showPage()
    page.save()
    return buffer.getvalue()
