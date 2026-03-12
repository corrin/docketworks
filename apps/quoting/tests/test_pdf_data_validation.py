from apps.client.models import Client
from apps.quoting.models import SupplierPriceList, SupplierProduct
from apps.quoting.services.pdf_data_validation import PDFDataValidationService
from apps.testing import BaseTestCase
from apps.workflow.models import CompanyDefaults


class PDFDataValidationServiceTest(BaseTestCase):
    """Test cases for PDFDataValidationService."""

    def setUp(self):
        """Set up test data."""
        self.service = PDFDataValidationService()

        # Get company defaults (singleton, loaded from fixture)
        self.company = CompanyDefaults.get_solo()

        # Create test supplier
        self.supplier = Client.objects.create(
            name="Test Supplier",
            is_supplier=True,
            xero_last_modified="2023-01-01T00:00:00Z",
        )

        # Create test price list
        self.price_list = SupplierPriceList.objects.create(
            supplier=self.supplier, file_name="test_price_list.pdf"
        )

    def test_validate_extracted_data_valid(self):
        """Test validation of valid extracted data."""
        data = {
            "supplier": {"name": self.company.company_name},
            "items": [
                {
                    "product_name": "Aluminum Angle",
                    "description": "25x25x3mm aluminum angle",
                    "item_no": "AL-ANG-001",
                    "unit_price": 12.50,
                    "price_unit": "per metre",
                }
            ],
        }

        is_valid, errors, warnings = self.service.validate_extracted_data(data)

        self.assertTrue(is_valid)
        self.assertEqual(len(errors), 0)
        self.assertEqual(len(warnings), 0)

    def test_validate_extracted_data_missing_supplier(self):
        """Test validation with missing supplier name."""
        data = {
            "supplier": {},
            "items": [
                {"product_name": "Test Product", "description": "Test description"}
            ],
        }

        is_valid, errors, warnings = self.service.validate_extracted_data(data)

        self.assertFalse(is_valid)
        self.assertIn("Missing supplier name", errors)

    def test_validate_extracted_data_no_items(self):
        """Test validation with no items."""
        data = {"supplier": {"name": self.company.company_name}, "items": []}

        is_valid, errors, warnings = self.service.validate_extracted_data(data)

        self.assertTrue(is_valid)  # No items is valid, just a warning
        self.assertIn("No items found in extracted data", warnings)

    def test_validate_extracted_data_invalid_items(self):
        """Test validation with invalid items."""
        data = {
            "supplier": {"name": self.company.company_name},
            "items": [
                {
                    # Missing both product_name and description
                    "item_no": "TEST-001"
                }
            ],
        }

        is_valid, errors, warnings = self.service.validate_extracted_data(data)

        self.assertFalse(is_valid)
        self.assertIn("No valid items found", errors)

    def test_normalize_price_valid_formats(self):
        """Test price normalization with various valid formats."""
        test_cases = [
            ("12.50", 12.50),
            ("$12.50", 12.50),
            ("£15.75", 15.75),
            ("1,234.56", 1234.56),
            ("10%", 0.10),
            ("50%", 0.50),
            ("  25.00  ", 25.00),
            (25.0, 25.0),
            (None, None),
            ("", None),
        ]

        for input_price, expected in test_cases:
            with self.subTest(input_price=input_price):
                result = self.service._normalize_price(input_price)
                self.assertEqual(result, expected)

    def test_normalize_price_invalid_formats(self):
        """Test price normalization with invalid formats."""
        invalid_prices = ["abc", "12.50.75", "$", "not-a-number"]

        for invalid_price in invalid_prices:
            with self.subTest(invalid_price=invalid_price):
                with self.assertRaises(ValueError):
                    self.service._normalize_price(invalid_price)

    def test_clean_text(self):
        """Test text cleaning functionality."""
        test_cases = [
            ("  Normal text  ", "Normal text"),
            ("Text\twith\ttabs", "Text with tabs"),
            ("Text\nwith\nnewlines", "Text with newlines"),  # All whitespace collapsed
            ("Text   with   spaces", "Text with spaces"),
            ("", ""),
            (None, ""),
            (123, "123"),
        ]

        for input_text, expected in test_cases:
            with self.subTest(input_text=input_text):
                result = self.service._clean_text(input_text)
                self.assertEqual(result, expected)

    def test_sanitize_product_data(self):
        """Test product data sanitization."""
        products = [
            {
                "product_name": "  Aluminum Angle  ",
                "description": "25x25x3mm\taluminum\tangle",
                "item_no": "AL-ANG-001",
                "unit_price": "$12.50",
                "price_unit": "per metre",
            },
            {
                # Missing product name, should use description
                "description": "Steel Bar",
                "unit_price": "15.75",
            },
            {
                # Invalid product - no name or description
                "item_no": "INVALID-001"
            },
        ]

        sanitized = self.service.sanitize_product_data(products)

        self.assertEqual(len(sanitized), 2)  # Third product should be filtered out

        # Check first product
        self.assertEqual(sanitized[0]["product_name"], "Aluminum Angle")
        self.assertEqual(sanitized[0]["description"], "25x25x3mm aluminum angle")
        self.assertEqual(sanitized[0]["unit_price"], 12.50)

        # Check second product (description used as product name)
        self.assertEqual(sanitized[1]["product_name"], "Steel Bar")
        self.assertEqual(sanitized[1]["unit_price"], 15.75)

    def test_check_duplicates_no_existing_supplier(self):
        """Test duplicate checking when supplier doesn't exist."""
        products = [{"product_name": "New Product", "item_no": "NEW-001"}]

        result = self.service.check_duplicates(products, "Nonexistent Supplier")

        self.assertEqual(len(result["duplicates"]), 0)
        self.assertEqual(len(result["new"]), 1)

    def test_check_duplicates_with_existing_products(self):
        """Test duplicate checking with existing products."""
        # Create existing product
        SupplierProduct.objects.create(
            supplier=self.supplier,
            price_list=self.price_list,
            product_name="Existing Product",
            item_no="EXIST-001",
            variant_id="EXIST-001-V1",
            url="",
        )

        products = [
            {
                "product_name": "Existing Product",
                "item_no": "EXIST-001",
            },  # Duplicate by item_no
            {
                "product_name": "existing product",
                "item_no": "DIFF-001",
            },  # Duplicate by name (case-insensitive)
            {"product_name": "New Product", "item_no": "NEW-001"},  # New product
        ]

        result = self.service.check_duplicates(products, self.supplier.name)

        self.assertEqual(len(result["duplicates"]), 2)
        self.assertEqual(len(result["new"]), 1)
        self.assertEqual(result["new"][0]["product_name"], "New Product")

    def test_validation_summary(self):
        """Test validation summary generation."""
        # Run validation that will generate errors and warnings
        data = {
            "supplier": {},  # Missing name - error
            "items": [
                {
                    "product_name": "Valid Product",
                    "unit_price": -10.0,  # Negative price - warning
                }
            ],
        }

        self.service.validate_extracted_data(data)
        summary = self.service.get_validation_summary()

        self.assertFalse(summary["is_valid"])
        self.assertEqual(summary["error_count"], 1)
        self.assertEqual(summary["warning_count"], 1)
        self.assertIn("Missing supplier name", summary["errors"])

    def test_long_field_truncation(self):
        """Test that long fields are properly truncated."""
        long_name = "A" * 600  # Longer than 500 char limit
        long_item_no = "B" * 150  # Longer than 100 char limit

        products = [
            {
                "product_name": long_name,
                "item_no": long_item_no,
                "description": "Test description",
            }
        ]

        sanitized = self.service.sanitize_product_data(products)

        self.assertEqual(len(sanitized[0]["product_name"]), 500)
        self.assertEqual(len(sanitized[0]["item_no"]), 100)

    def test_variant_id_generation(self):
        """Test automatic variant_id generation when missing."""
        products = [
            {"product_name": "Product 1", "description": "First product"},
            {"product_name": "Product 2", "description": "Second product"},
        ]

        sanitized = self.service.sanitize_product_data(products)

        self.assertEqual(sanitized[0]["variant_id"], "ITEM-0000")
        self.assertEqual(sanitized[1]["variant_id"], "ITEM-0001")
