"""Inspection of provider-rendered quote PDFs."""

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from pypdf import PdfReader

from apps.accounting.registry import get_provider
from apps.core.models import CompanyDefaults


@dataclass(frozen=True)
class QuotePdfInspection:
    """Structured evidence from a provider-rendered quote PDF."""

    quote_id: str
    remote_branding_theme_id: str | None
    configured_branding_theme_id: str | None
    page_count: int
    contains_expected_text: bool


def inspect_quote_pdf(quote_id: UUID, expected_text: str) -> QuotePdfInspection:
    """Inspect the real provider PDF without exposing its customer text."""
    normalized_expected_text = " ".join(expected_text.split())
    if not normalized_expected_text:
        raise ValueError("Expected quote PDF text must not be empty")

    provider = get_provider()
    document = provider.download_quote_pdf(str(quote_id))
    reader = PdfReader(document.temporary_file_path)
    page_text: list[str] = []
    for page in reader.pages:
        extracted = page.extract_text()
        # A blank or image-only page extracts to "" — keep only pages with real
        # text so an all-blank PDF raises below rather than reporting the marker
        # absent and deleting the diagnostic file.
        if extracted is not None and extracted.strip():
            page_text.append(extracted)

    if not page_text:
        raise ValueError(f"Quote {quote_id} PDF contains no extractable text")

    # Xero's text layer sometimes wraps mid-phrase and sometimes drops word
    # spaces entirely — match both the space-normalised and compact forms so
    # neither rendering quirk reads as missing terms.
    normalized_document_text = " ".join("\n".join(page_text).split())
    compact_expected_text = "".join(normalized_expected_text.split())
    compact_document_text = "".join(normalized_document_text.split())
    configured_theme_id = CompanyDefaults.get_solo().xero_sales_branding_theme_id
    inspection = QuotePdfInspection(
        quote_id=document.external_id,
        remote_branding_theme_id=document.document_theme_external_id,
        configured_branding_theme_id=(
            str(configured_theme_id) if configured_theme_id is not None else None
        ),
        page_count=len(reader.pages),
        contains_expected_text=(
            normalized_expected_text in normalized_document_text
            or compact_expected_text in compact_document_text
        ),
    )
    # Only when the marker was FOUND: an absent marker is exactly the case an
    # operator needs the rendered PDF for, so it keeps the file just like the
    # exception paths above do. (Improves on the ported behaviour, which
    # deleted the file in its own diagnostic case.)
    if inspection.contains_expected_text:
        Path(document.temporary_file_path).unlink(missing_ok=True)
    return inspection
