"""PDF PRICE-LIST EXTRACTION SEAM — v1's OCR/vision upload pipeline is NOT ported.

Deferred deliberately in the Phase 3c-3 quoting slice. This module exists so the
decision has a name — a searchable home and a loud failure — instead of being a
silently missing feature.

WHAT IS MISSING (v1 files, ~1,300 lines):

- ``apps/quoting/views.py::extract_supplier_price_list_data_view`` — POST
  ``/api/quoting/extract-supplier-price-list/``, a multipart PDF upload.
- ``apps/quoting/services/ai_price_extraction.py`` — provider factory and the
  Mistral-then-Gemini priority order.
- ``apps/quoting/services/providers/gemini_provider.py`` (622 lines) and
  ``providers/mistral_provider.py`` (396 lines) — the vision/OCR adapters.
- ``apps/quoting/services/pdf_data_validation.py`` and
  ``services/pdf_import_service.py`` — validation, sanitisation, and the
  supplier/price-list/product import that only this endpoint reaches.
- ``apps/quoting/serializers.py`` — request/response shapes for that view.

WHY IT WAS DEFERRED:

1. Nothing consumes it. The endpoint is a plain ``@require_http_methods``
   function view, so drf-spectacular never emitted it: it is absent from
   ``frontend/schema.yml``, and no v1 frontend module posts to it (the v1
   ``frontend/src`` tree has zero references to the path or to
   ``price_list_file``). It is not part of the API contract v2 is porting.
2. It needs two vendor SDKs v2 does not have — ``google-generativeai`` and
   ``mistralai`` — on top of the ``litellm`` boundary the product parser already
   needs. Dependencies are the user's call, and one is cheaper to weigh than
   three.
3. The surface that reviews its output — ``/api/purchasing/supplier-price-status/``
   and ``/api/purchasing/product-mappings/`` — is already ported and is fed by
   the scraper path (``apps/quoting/scrapers``) plus
   ``product_parser.create_mapping_record``. Deferring this pipeline leaves no
   ported endpoint reading an empty table.
4. Its two duplicate-detection implementations
   (``PDFDataValidationService.check_duplicates`` and
   ``PDFImportService.handle_duplicates``) are exactly the ADR 0039 pathology.
   Porting it means arbitrating those first, which is a conversation, not a
   translation.

TO PICK IT UP: port ``pdf_data_validation`` and ``pdf_import_service`` first
(pure functions and pure ORM, no SDK, directly testable), collapsing the two
duplicate checks into one; then add the SDK adapters behind
``extract_price_data`` below; then expose the endpoint on the quoting router.
``PDFImportService._create_new_product`` must call
``product_parser.create_mapping_record`` exactly as the scraper path does — that
is the join that makes uploaded products reviewable.
"""

from pathlib import Path


class PriceExtractionNotPortedError(NotImplementedError):
    """Raised by the seam below; this module's docstring is the full note."""


def extract_price_data(file_path: Path, content_type: str) -> None:
    """Raise the seam error. Named after v1's ``ai_price_extraction.extract_price_data``.

    v1 returned ``(data | None, error | None)`` and every caller re-checked both
    halves. This raises instead, so a future port starts from a shape that
    cannot reintroduce the silent-``None`` branch (ADR 0038).
    """
    raise PriceExtractionNotPortedError(
        f"PDF PRICE-LIST EXTRACTION SEAM: extracting {file_path.name} ({content_type}) "
        f"needs v1's Gemini/Mistral OCR providers, which the Phase 3c-3 quoting slice "
        f"deliberately did not port. See apps/quoting/services/price_extraction.py."
    )
