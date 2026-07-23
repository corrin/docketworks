import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from apps.quoting.services.pdf_data_validation import PDFDataValidationService
from apps.quoting.services.providers.mistral_provider import (
    MistralPriceExtractionProvider,
)


class TestOCRFixtures(unittest.TestCase):
    def _ocr_response(self):
        page = SimpleNamespace(
            markdown=(
                "Customer: | Morris Sheetmetal |\n"
                "Date: | 2026-05-22 |\n\n"
                "# Aluminium Sheet\n\n"
                "| Description | Price |\n"
                "| --- | --- |\n"
                "| 1.2mm x 1200 x 2400 5005 Sheet | $71.07 |\n"
                "| 2.0mm x 1200 x 2400 5005 Sheet | $113.71 |\n\n"
                "**WM Aluminium Ltd**"
            ),
            text="",
        )
        return SimpleNamespace(pages=[page])

    def _ocr_response_with_item_code(self) -> SimpleNamespace:
        """As above, but with a supplier item code in the description.

        The main fixture's descriptions carry no code, so item_no is legitimately
        empty there and cannot show whether the code survives the import.
        """
        page = SimpleNamespace(
            markdown=(
                "Customer: | Morris Sheetmetal |\n"
                "Date: | 2026-05-22 |\n\n"
                "# Aluminium Sheet\n\n"
                "| Description | Price |\n"
                "| --- | --- |\n"
                "| UA1130 1.2mm x 1200 x 2400 5005 Sheet | $71.07 |\n\n"
                "**WM Aluminium Ltd**"
            ),
            text="",
        )
        return SimpleNamespace(pages=[page])

    @patch("apps.quoting.services.providers.mistral_provider.Mistral")
    def test_price_parsing_with_mocked_ocr_response(self, mock_mistral_class):
        """Catches OCR parser drift without making a live Mistral API call."""
        mock_client = Mock()
        mock_client.ocr.process.return_value = self._ocr_response()
        mock_mistral_class.return_value = mock_client
        provider = MistralPriceExtractionProvider(api_key="dummy_key_for_testing")

        with (
            patch(
                "apps.quoting.services.providers.mistral_provider.os.path.exists",
                return_value=True,
            ),
            patch(
                "apps.quoting.services.providers.mistral_provider.encode_pdf",
                return_value="mock_base64",
            ),
        ):
            result, error = provider.extract_price_data("mock_file_path.pdf")

        self.assertIsNone(error)
        self.assertIsNotNone(result)
        assert result is not None

        self.assertEqual(
            result["supplier"],
            {
                "name": "WM Aluminium Ltd",
                "customer": "Morris Sheetmetal",
                "date": "2026-05-22",
            },
        )
        self.assertIn("1.2mm x 1200 x 2400 5005 Sheet", result["raw_ocr_text"])
        self.assertEqual(
            result["parsing_stats"],
            {
                "total_lines": 12,
                "items_found": 2,
                "pages_processed": 1,
            },
        )

        first_item = result["items"][0]
        self.assertEqual(
            first_item,
            {
                "description": "1.2mm x 1200 x 2400 5005 Sheet",
                "item_no": "",
                "variant_id": "1.2mm_x_1200_x_2400_5005_Sheet",
                "unit_price": 71.07,
                "price_unit": "each",
                "category": "Aluminium Sheet",
                "specifications": "1.2mm x 1200 x 2400 5005 Sheet",
                "dimensions": "1.2mm x 1200 x 2400",
                "product_name": ("Aluminium Sheet - 1.2mm x 1200 x 2400 5005 Sheet"),
            },
        )

    @patch("apps.quoting.services.providers.mistral_provider.Mistral")
    def test_extracted_items_survive_the_import_sanitiser(
        self, mock_mistral_class: Mock
    ) -> None:
        """The import sanitiser must keep the fields Mistral extracts.

        The provider names its fields for
        PDFDataValidationService._sanitize_single_product, and a mismatch is
        silent — the field is simply absent from the sanitised product. So this
        asserts across that boundary, on the last hop before import, rather
        than on the provider's own dict, which would agree with itself after a
        rename.
        """
        mock_client = Mock()
        mock_client.ocr.process.return_value = self._ocr_response_with_item_code()
        mock_mistral_class.return_value = mock_client
        provider = MistralPriceExtractionProvider(api_key="dummy_key_for_testing")

        with (
            patch(
                "apps.quoting.services.providers.mistral_provider.os.path.exists",
                return_value=True,
            ),
            patch(
                "apps.quoting.services.providers.mistral_provider.encode_pdf",
                return_value="mock_base64",
            ),
        ):
            result, error = provider.extract_price_data("mock_file_path.pdf")

        self.assertIsNone(error)
        assert result is not None

        sanitised = PDFDataValidationService().sanitize_product_data(result["items"])

        self.assertEqual(sanitised[0]["item_no"], "UA1130")
        self.assertEqual(sanitised[0]["dimensions"], "1.2mm x 1200 x 2400")


if __name__ == "__main__":
    unittest.main()
