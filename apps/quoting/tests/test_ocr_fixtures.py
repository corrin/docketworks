import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

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
                "supplier_item_code": "",
                "variant_id": "1.2mm_x_1200_x_2400_5005_Sheet",
                "unit_price": 71.07,
                "category": "Aluminium Sheet",
                "specifications": "1.2mm x 1200 x 2400 5005 Sheet",
                "dimensions": {
                    "width": "1200",
                    "length": "2400",
                    "thickness": "1.2mm",
                    "diameter": None,
                },
                "product_name": ("Aluminium Sheet - 1.2mm x 1200 x 2400 5005 Sheet"),
            },
        )


if __name__ == "__main__":
    unittest.main()
