"""Inspection of provider-rendered quote PDFs."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from pypdf import PdfReader

from apps.workflow.accounting.registry import get_provider
from apps.workflow.models import CompanyDefaults
from apps.workflow.services.error_persistence import persist_app_error


@dataclass(frozen=True)
class QuotePdfInspection:
    """Structured evidence from a provider-rendered quote PDF."""

    quote_id: str
    remote_branding_theme_id: str | None
    configured_branding_theme_id: str | None
    page_count: int
    contains_expected_text: bool


def inspect_quote_pdf(
    quote_id: UUID,
    expected_text: str,
) -> QuotePdfInspection:
    """Inspect the real provider PDF without exposing its customer text."""
    normalized_expected_text = " ".join(expected_text.split())
    if not normalized_expected_text:
        raise ValueError("Expected quote PDF text must not be empty")

    document = None
    try:
        provider = get_provider()
        document = provider.download_quote_pdf(str(quote_id))
        reader = PdfReader(document.temporary_file_path)
        page_text: list[str] = []
        for page in reader.pages:
            extracted = page.extract_text()
            if extracted is not None:
                page_text.append(extracted)

        if not page_text:
            raise ValueError(f"Quote {quote_id} PDF contains no extractable text")

        normalized_document_text = " ".join("\n".join(page_text).split())
        compact_expected_text = "".join(normalized_expected_text.split())
        compact_document_text = "".join(normalized_document_text.split())
        configured_theme_id = CompanyDefaults.get_solo().xero_sales_branding_theme_id
        return QuotePdfInspection(
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
    except Exception as exc:
        persist_app_error(exc)
        raise
    finally:
        if document is not None:
            try:
                document.temporary_file_path.unlink(missing_ok=True)
            except Exception as exc:
                persist_app_error(exc)
                raise
