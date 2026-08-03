"""The PDF price-list extraction seam stays a seam, and stays loud.

``apps/quoting/services/price_extraction.py`` is a deliberate deferral, not an
implementation: v1's ~1,300-line Gemini/Mistral OCR upload pipeline is not
ported. Its module docstring carries the reasoning and the pick-up
instructions; this file guards the two properties that make a deferral safe
rather than a hole:

1. reaching it fails immediately, by a named type, with a message that says
   which v1 code is missing and where the note lives — it never returns an
   empty result that a caller might mistake for "this PDF had no prices"
   (ADR 0038);
2. it reaches no vendor SDK. Whenever the pipeline is picked up it goes through
   ``apps.ai``'s gateway like everything else (ADR 0041) — v1 grew a
   ``genai.Client`` and a ``Mistral()`` here, which is half of why that ADR
   exists.
"""

import inspect
from pathlib import Path

import pytest

from apps.quoting.services import price_extraction
from apps.quoting.services.price_extraction import (
    PriceExtractionNotPortedError,
    extract_price_data,
)

VENDOR_SDKS = ("genai", "google.generativeai", "mistralai", "anthropic", "openai")


class TestTheSeamIsLoud:
    def test_calling_it_raises_rather_than_returning_nothing(self) -> None:
        with pytest.raises(PriceExtractionNotPortedError) as raised:
            extract_price_data(Path("uploads/steel-and-tube-prices.pdf"), "application/pdf")

        message = str(raised.value)
        assert "steel-and-tube-prices.pdf" in message
        assert "application/pdf" in message
        assert "apps/quoting/services/price_extraction.py" in message

    def test_the_error_is_a_not_implemented_error_so_generic_handlers_treat_it_as_one(
        self,
    ) -> None:
        assert issubclass(PriceExtractionNotPortedError, NotImplementedError)

    def test_the_note_says_what_is_missing_and_how_to_pick_it_up(self) -> None:
        """The module docstring IS the deferral record; an empty one is a hole."""
        docstring = inspect.getdoc(price_extraction)

        assert docstring is not None
        assert "WHAT IS MISSING" in docstring
        assert "WHY IT WAS DEFERRED" in docstring
        assert "TO PICK IT UP" in docstring


class TestTheSeamPullsInNoVendorSdk:
    def test_the_module_imports_no_model_vendors_sdk(self) -> None:
        """ADR 0041: the pick-up goes through apps.ai, not a fourth local client."""
        source = Path(inspect.getfile(price_extraction)).read_text()
        code = source.replace(inspect.getdoc(price_extraction) or "", "")

        for sdk in VENDOR_SDKS:
            assert f"import {sdk}" not in code
