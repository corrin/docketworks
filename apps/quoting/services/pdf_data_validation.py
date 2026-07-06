import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from apps.company.models import Company
from apps.quoting.models import SupplierProduct

logger = logging.getLogger(__name__)


class PDFDataValidationService:
    """
    Service for validating and sanitizing extracted PDF data before import.

    Handles validation of required fields, data sanitization, price normalization,
    and duplicate detection for supplier products.
    """

    def __init__(self):
        self.validation_errors = []
        self.warnings = []

    def validate_extracted_data(
        self, data: Dict[str, Any]
    ) -> Tuple[bool, List[str], List[str]]:
        """
        Validate the complete extracted data structure.

        Args:
            data: Extracted data dictionary from AI processing

        Returns:
            Tuple of (is_valid, errors, warnings)
        """
        self.validation_errors = []
        self.warnings = []

        # Validate top-level structure
        if not isinstance(data, dict):
            self.validation_errors.append("Invalid data format: expected dictionary")
            return False, self.validation_errors, self.warnings

        # Validate supplier information
        supplier_info = data.get("supplier", {})
        if not supplier_info.get("name"):
            self.validation_errors.append("Missing supplier name")

        # Validate items array
        items = data.get("items", [])
        if not isinstance(items, list):
            self.validation_errors.append("Invalid items format: expected list")
            return False, self.validation_errors, self.warnings

        if not items:
            self.warnings.append("No items found in extracted data")

        # Validate each item
        valid_items = 0
        for idx, item in enumerate(items):
            if self._validate_single_item(item, idx):
                valid_items += 1

        if valid_items == 0 and items:
            self.validation_errors.append("No valid items found")
        elif valid_items < len(items):
            self.warnings.append(
                f"Only {valid_items} out of {len(items)} items are valid"
            )

        is_valid = len(self.validation_errors) == 0
        return is_valid, self.validation_errors, self.warnings

    def _validate_single_item(self, item: Dict[str, Any], index: int) -> bool:
        """
        Validate a single product item.

        Args:
            item: Product item dictionary
            index: Item index for error reporting

        Returns:
            True if item is valid, False otherwise
        """
        item_valid = True

        # Check required fields
        product_name = item.get("product_name", "").strip()
        description = item.get("description", "").strip()

        if not product_name and not description:
            self.validation_errors.append(
                f"Item {index}: Missing both product name and description"
            )
            item_valid = False

        # Validate price if present
        unit_price = item.get("unit_price")
        if unit_price is not None:
            try:
                normalized_price = self._normalize_price(unit_price)
                if normalized_price is not None and normalized_price < 0:
                    self.warnings.append(
                        f"Item {index}: Negative price {normalized_price}"
                    )
            except ValueError as e:
                self.warnings.append(
                    f"Item {index}: Invalid price format '{unit_price}': {e}"
                )

        # Validate item code format if present
        item_no = item.get("item_no", "").strip()
        if item_no and len(item_no) > 100:
            self.warnings.append(f"Item {index}: Item code too long, will be truncated")

        # Validate text field lengths
        if product_name and len(product_name) > 500:
            self.warnings.append(
                f"Item {index}: Product name too long, will be truncated"
            )

        return item_valid

    def sanitize_product_data(
        self, products: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Clean and normalize product data for database insertion.

        Args:
            products: List of product dictionaries

        Returns:
            List of sanitized product dictionaries
        """
        sanitized_products = []

        for idx, product in enumerate(products):
            try:
                sanitized = self._sanitize_single_product(product, idx)
                if sanitized:
                    sanitized_products.append(sanitized)
            except Exception as e:
                logger.error(f"Error sanitizing product {idx}: {e}")
                continue

        return sanitized_products

    def _sanitize_single_product(
        self, product: Dict[str, Any], index: int
    ) -> Optional[Dict[str, Any]]:
        """
        Sanitize a single product dictionary.

        Args:
            product: Product dictionary
            index: Product index for logging

        Returns:
            Sanitized product dictionary or None if invalid
        """
        # Extract and clean basic fields
        product_name = self._clean_text(product.get("product_name", ""))
        description = self._clean_text(product.get("description", ""))

        # Skip if no meaningful content
        if not product_name and not description:
            logger.warning(f"Skipping product {index}: no product name or description")
            return None

        # Use description as product name if product name is missing
        if not product_name and description:
            product_name = description

        # Clean and validate other fields
        item_no = self._clean_text(product.get("item_no", ""))
        specifications = self._clean_text(product.get("specifications", ""))

        # Generate variant_id if missing
        variant_id = product.get("variant_id", "").strip()
        if not variant_id:
            variant_id = f"ITEM-{index:04d}"

        # Normalize price
        unit_price = None
        price_str = product.get("unit_price")
        if price_str is not None:
            try:
                unit_price = self._normalize_price(price_str)
            except ValueError:
                logger.warning(f"Product {index}: Could not parse price '{price_str}'")

        # Clean price unit
        price_unit = self._clean_text(product.get("price_unit", "each"))
        if not price_unit:
            price_unit = "each"

        return {
            "product_name": product_name[:500],  # Truncate to database limit
            "description": description,
            "item_no": item_no[:100],  # Truncate to database limit
            "specifications": specifications,
            "variant_id": variant_id[:100],  # Truncate to database limit
            "unit_price": unit_price,
            "price_unit": price_unit[:50],  # Truncate to database limit
            "dimensions": self._clean_text(product.get("dimensions", "")),
        }

    def _clean_text(self, text: Any) -> str:
        """
        Clean and normalize text fields.

        Args:
            text: Text to clean

        Returns:
            Cleaned text string
        """
        if text is None:
            return ""

        # Convert to string and strip whitespace
        text = str(text).strip()

        # Collapse all whitespace (spaces, tabs, newlines) to single space
        text = re.sub(r"\s+", " ", text)

        # Remove control characters
        text = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]", "", text)

        return text

    def _normalize_price(self, price: Any) -> Optional[float]:
        """
        Normalize price values to float.

        Args:
            price: Price value in various formats

        Returns:
            Normalized price as float or None if invalid

        Raises:
            ValueError: If price cannot be parsed
        """
        if price is None or price == "":
            return None

        # Convert to string for processing
        price_str = str(price).strip()

        if not price_str:
            return None

        # Remove currency symbols and common formatting
        price_str = re.sub(r"[$£€¥₹]", "", price_str)  # Remove currency symbols
        price_str = re.sub(r"[,\s]", "", price_str)  # Remove commas and spaces

        # Handle percentage (convert to decimal)
        if price_str.endswith("%"):
            price_str = price_str[:-1]
            try:
                return float(price_str) / 100.0
            except ValueError:
                raise ValueError(f"Invalid percentage format: {price}")

        # Try to convert to float
        try:
            return float(price_str)
        except ValueError:
            raise ValueError(f"Cannot parse price: {price}")

    def check_duplicates(
        self, products: List[Dict[str, Any]], supplier_name: str
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Check for duplicate products against existing database records.

        Args:
            products: List of product dictionaries to check
            supplier_name: Name of the supplier

        Returns:
            Dictionary with 'duplicates' and 'new' product lists
        """
        try:
            supplier = Company.objects.get(name=supplier_name)
        except Company.DoesNotExist:
            # If supplier doesn't exist, all products are new
            return {"duplicates": [], "new": products}

        duplicates = []
        new_products = []

        # Get existing products for this supplier
        existing_products = SupplierProduct.objects.filter(supplier=supplier)
        existing_item_nos = set(p.item_no for p in existing_products if p.item_no)
        existing_names = set(
            p.product_name.lower() for p in existing_products if p.product_name
        )

        for product in products:
            is_duplicate = False

            # Check by item number
            item_no = product.get("item_no", "").strip()
            if item_no and item_no in existing_item_nos:
                is_duplicate = True

            # Check by product name (case-insensitive)
            product_name = product.get("product_name", "").strip().lower()
            if not is_duplicate and product_name and product_name in existing_names:
                is_duplicate = True

            if is_duplicate:
                duplicates.append(product)
            else:
                new_products.append(product)

        return {"duplicates": duplicates, "new": new_products}

    def get_validation_summary(self) -> Dict[str, Any]:
        """
        Get a summary of the last validation run.

        Returns:
            Dictionary with validation summary
        """
        return {
            "errors": self.validation_errors,
            "warnings": self.warnings,
            "error_count": len(self.validation_errors),
            "warning_count": len(self.warnings),
            "is_valid": len(self.validation_errors) == 0,
        }
