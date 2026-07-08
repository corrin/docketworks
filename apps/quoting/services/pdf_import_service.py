import logging
from typing import Dict, List, Tuple

from django.db import transaction
from django.utils import timezone

from apps.company.models import Company
from apps.quoting.models import SupplierPriceList, SupplierProduct
from apps.quoting.services.product_parser import create_mapping_record

logger = logging.getLogger(__name__)


class PDFImportService:
    """
    Service for handling atomic database operations during PDF import.

    Manages supplier creation, price list creation, and bulk product import
    with proper error handling and transaction management.
    """

    def __init__(self):
        self.import_stats = {
            "supplier_created": False,
            "price_list_created": False,
            "products_imported": 0,
            "products_failed": 0,
            "errors": [],
        }

    def create_or_get_supplier(self, supplier_name: str) -> Tuple[Company, bool]:
        """
        Create or retrieve supplier company record.

        Args:
            supplier_name: Name of the supplier

        Returns:
            Tuple of (Company instance, was_created boolean)
        """
        try:
            supplier = Company.objects.get(name=supplier_name)
            logger.info(f"Found existing supplier: {supplier.name} (ID: {supplier.id})")
            return supplier, False
        except Company.DoesNotExist:
            # Create new supplier
            supplier = Company.objects.create(
                name=supplier_name, is_supplier=True, xero_last_modified=timezone.now()
            )
            logger.info(f"Created new supplier: {supplier.name} (ID: {supplier.id})")
            self.import_stats["supplier_created"] = True
            return supplier, True

    def create_price_list(self, supplier: Company, filename: str) -> SupplierPriceList:
        """
        Create a new price list record for the supplier.

        Args:
            supplier: Supplier company instance
            filename: Original filename of the uploaded PDF

        Returns:
            SupplierPriceList instance
        """
        price_list = SupplierPriceList.objects.create(
            supplier=supplier, file_name=filename
        )
        logger.info(f"Created price list: {price_list.id} for supplier {supplier.name}")
        self.import_stats["price_list_created"] = True
        return price_list

    @transaction.atomic
    def import_products(
        self,
        products: List[Dict],
        supplier: Company,
        price_list: SupplierPriceList,
        duplicate_strategy: str = "skip",
    ) -> Dict[str, int]:
        """
        Import products to database with atomic transaction.

        Args:
            products: List of sanitized product dictionaries
            supplier: Supplier company instance
            price_list: Price list instance
            duplicate_strategy: How to handle duplicates ("skip", "update", "create_new")

        Returns:
            Dictionary with import statistics
        """
        imported_count = 0
        failed_count = 0
        updated_count = 0
        skipped_count = 0

        logger.info(f"Starting import of {len(products)} products for {supplier.name}")
        logger.info(
            f"Sample product data: {products[0] if products else 'No products'}"
        )

        for idx, product_data in enumerate(products):
            try:
                logger.debug(
                    f"Processing product {idx}: {product_data.get('product_name', 'Unknown')}"
                )
                result = self._import_single_product(
                    product_data, supplier, price_list, duplicate_strategy, idx
                )

                if result == "imported":
                    imported_count += 1
                elif result == "updated":
                    updated_count += 1
                elif result == "skipped":
                    skipped_count += 1

                # Log progress every 50 items
                if (imported_count + updated_count + skipped_count) % 50 == 0:
                    logger.info(
                        f"Import progress: {imported_count + updated_count + skipped_count}/{len(products)} processed"
                    )

            except Exception as e:
                failed_count += 1
                error_msg = f"Failed to import product {idx}: {str(e)}"
                logger.error(error_msg)
                self.import_stats["errors"].append(error_msg)

                # Continue with other products rather than failing entire import
                continue

        # Update import statistics
        self.import_stats.update(
            {
                "products_imported": imported_count,
                "products_updated": updated_count,
                "products_skipped": skipped_count,
                "products_failed": failed_count,
            }
        )

        logger.info(
            f"Import completed: {imported_count} imported, {updated_count} updated, "
            f"{skipped_count} skipped, {failed_count} failed"
        )

        return {
            "imported": imported_count,
            "updated": updated_count,
            "skipped": skipped_count,
            "failed": failed_count,
        }

    def _import_single_product(
        self,
        product_data: Dict,
        supplier: Company,
        price_list: SupplierPriceList,
        duplicate_strategy: str,
        index: int,
    ) -> str:
        """
        Import a single product with duplicate handling.

        Args:
            product_data: Sanitized product data dictionary
            supplier: Supplier company instance
            price_list: Price list instance
            duplicate_strategy: How to handle duplicates
            index: Product index for logging

        Returns:
            String indicating the action taken ("imported", "updated", "skipped")
        """
        # Check for existing product
        existing_product = self._find_existing_product(product_data, supplier)

        if existing_product:
            return self._handle_duplicate_product(
                existing_product, product_data, duplicate_strategy, index
            )
        else:
            # Create new product
            return self._create_new_product(product_data, supplier, price_list, index)

    def _find_existing_product(
        self, product_data: Dict, supplier: Company
    ) -> SupplierProduct:
        """
        Find existing product by item_no or product_name.

        Args:
            product_data: Product data dictionary
            supplier: Supplier company instance

        Returns:
            Existing SupplierProduct instance or None
        """
        item_no = product_data.get("item_no", "").strip()
        product_name = product_data.get("product_name", "").strip()

        # First try to find by item_no (more specific)
        if item_no:
            try:
                return SupplierProduct.objects.get(supplier=supplier, item_no=item_no)
            except SupplierProduct.DoesNotExist:
                pass

        # Then try by product_name (case-insensitive)
        if product_name:
            try:
                return SupplierProduct.objects.get(
                    supplier=supplier, product_name__iexact=product_name
                )
            except SupplierProduct.DoesNotExist:
                pass

        return None

    def _handle_duplicate_product(
        self,
        existing_product: SupplierProduct,
        product_data: Dict,
        strategy: str,
        index: int,
    ) -> str:
        """
        Handle duplicate product based on strategy.

        Args:
            existing_product: Existing SupplierProduct instance
            product_data: New product data
            strategy: Duplicate handling strategy
            index: Product index for logging

        Returns:
            String indicating action taken
        """
        if strategy == "skip":
            logger.debug(
                f"Skipping duplicate product {index}: {existing_product.product_name}"
            )
            return "skipped"

        elif strategy == "update":
            # Update existing product with new data
            self._update_existing_product(existing_product, product_data)
            logger.info(
                f"Updated existing product {index}: {existing_product.product_name}"
            )
            return "updated"

        elif strategy == "create_new":
            # Create new product with modified variant_id to avoid conflicts
            product_data["variant_id"] = f"{product_data['variant_id']}-NEW-{index}"
            return self._create_new_product(
                product_data,
                existing_product.supplier,
                existing_product.price_list,
                index,
            )

        else:
            logger.warning(
                f"Unknown duplicate strategy '{strategy}', skipping product {index}"
            )
            return "skipped"

    def _update_existing_product(
        self, existing_product: SupplierProduct, product_data: Dict
    ):
        """
        Update existing product with new data.

        Args:
            existing_product: Existing SupplierProduct instance
            product_data: New product data dictionary
        """
        # Update fields but preserve created_at timestamp
        existing_product.description = product_data.get(
            "description", existing_product.description
        )
        existing_product.specifications = product_data.get(
            "specifications", existing_product.specifications
        )
        existing_product.variant_price = product_data.get(
            "unit_price", existing_product.variant_price
        )
        existing_product.price_unit = product_data.get(
            "price_unit", existing_product.price_unit
        )

        # Update timestamp
        existing_product.updated_at = timezone.now()
        existing_product.save()

        # Create new mapping record for updated product
        create_mapping_record(existing_product)

    def _create_new_product(
        self,
        product_data: Dict,
        supplier: Company,
        price_list: SupplierPriceList,
        index: int,
    ) -> str:
        """
        Create a new product record.

        Args:
            product_data: Product data dictionary
            supplier: Supplier company instance
            price_list: Price list instance
            index: Product index for logging

        Returns:
            String indicating action taken ("imported")
        """
        # Create the product
        logger.debug(f"Creating product with data: {product_data}")
        try:
            product = SupplierProduct.objects.create(
                supplier=supplier,
                price_list=price_list,
                product_name=product_data["product_name"],
                item_no=product_data.get("item_no", ""),
                description=product_data.get("description", ""),
                specifications=product_data.get("specifications", ""),
                variant_id=product_data["variant_id"],
                variant_price=product_data.get("unit_price"),
                price_unit=product_data.get("price_unit", "each"),
                variant_available_stock=0,  # PDF doesn't have stock info
                url="",  # PDF doesn't have URLs
            )
            logger.debug(f"Successfully created product: {product.id}")
        except Exception as create_error:
            logger.error(f"Failed to create product: {create_error}")
            logger.error(f"Product data: {product_data}")
            raise

        # Create mapping record for LLM processing
        create_mapping_record(product)

        logger.debug(f"Created new product {index}: {product.product_name}")
        return "imported"

    def handle_duplicates(
        self, products: List[Dict], supplier_name: str, strategy: str = "skip"
    ) -> Dict:
        """
        Analyze and handle duplicate products before import.

        Args:
            products: List of product dictionaries
            supplier_name: Name of the supplier
            strategy: How to handle duplicates

        Returns:
            Dictionary with duplicate analysis results
        """
        try:
            supplier = Company.objects.get(name=supplier_name)
        except Company.DoesNotExist:
            # No supplier exists, so no duplicates possible
            return {
                "duplicates_found": 0,
                "new_products": len(products),
                "action": "all_new",
            }

        duplicates = []
        new_products = []

        for product in products:
            existing = self._find_existing_product(product, supplier)
            if existing:
                duplicates.append(
                    {
                        "new_product": product,
                        "existing_product": {
                            "id": existing.id,
                            "product_name": existing.product_name,
                            "item_no": existing.item_no,
                            "price": (
                                float(existing.variant_price)
                                if existing.variant_price
                                else None
                            ),
                            "updated_at": existing.updated_at.isoformat(),
                        },
                    }
                )
            else:
                new_products.append(product)

        return {
            "duplicates_found": len(duplicates),
            "new_products": len(new_products),
            "duplicates": duplicates,
            "strategy": strategy,
            "action": f"will_{strategy}_duplicates",
        }

    def get_import_stats(self) -> Dict:
        """
        Get import statistics from the last import operation.

        Returns:
            Dictionary with import statistics
        """
        return self.import_stats.copy()

    def reset_stats(self):
        """Reset import statistics."""
        self.import_stats = {
            "supplier_created": False,
            "price_list_created": False,
            "products_imported": 0,
            "products_failed": 0,
            "errors": [],
        }
