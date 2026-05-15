import json
import logging
from decimal import Decimal
from typing import Any, Dict, Optional, Tuple

from django.utils import timezone

from apps.job.enums import MetalType
from apps.quoting.models import ProductParsingMapping, SupplierProduct
from apps.quoting.utils import (
    calculate_product_mapping_hash,
    calculate_supplier_product_hash,
)
from apps.workflow.enums import AIProviderTypes
from apps.workflow.services.llm_service import LLMService

logger = logging.getLogger(__name__)

ParsedProductResult = Tuple[Dict[str, Any], bool]


class ProductParser:
    """
    Optimistic parser that maps supplier product data to inventory format
    using LLM with permanent mapping storage for consistency.
    """

    PARSER_VERSION = "1.1.0"
    BATCH_SIZE = 100

    def __init__(self) -> None:
        """Initialize parser with LLM service."""
        # Use the shared LLMService - prefer Google/Gemini Flash models for parsing
        # as they are cheaper and faster while sufficient for this task
        self.llm = LLMService(provider_type=AIProviderTypes.GOOGLE)

    def _calculate_input_hash(self, product_data: Dict[str, Any]) -> str:
        """Calculate SHA-256 hash based on description only."""
        return calculate_product_mapping_hash(product_data)

    def _get_cached_mapping(self, input_hash: str) -> Optional[ProductParsingMapping]:
        """Retrieve existing mapping from database."""
        try:
            return ProductParsingMapping.objects.get(input_hash=input_hash)
        except ProductParsingMapping.DoesNotExist:
            return None

    def _get_training_examples(self) -> str:
        """Get few-shot training examples for the LLM."""
        return """
TRAINING EXAMPLES:

Example 1:
INPUT: Product Name: 30mm x 10mm 304 HRAP Stainless Steel Flat Bar ASTM A276
       Description: 30mm x 10mm 304 HRAP Stainless Steel Flat Bar ASTM A276
       Price: 45.20 per metre
OUTPUT: {
    "item_code": "FB-3010-304HRAP",
    "description": "30mm x 10mm 304 HRAP Stainless Steel Flat Bar",
    "metal_type": "stainless_steel",
    "alloy": "304",
    "specifics": "HRAP finish, ASTM A276",
    "dimensions": "30x10mm",
    "unit_cost": 45.20,
    "price_unit": "per metre",
    "confidence": 0.95
}

Example 2:
INPUT: Product Name: 6061 T6 Aluminium Round Bar 25mm Diameter
       Description: 6061 T6 Aluminium Round Bar 25mm Diameter
       Price: 12.50 each
OUTPUT: {
    "item_code": "RB-25-6061T6",
    "description": "25mm Diameter 6061 T6 Aluminium Round Bar",
    "metal_type": "aluminium",
    "alloy": "6061",
    "specifics": "T6 temper",
    "dimensions": "25mm diameter",
    "unit_cost": 12.50,
    "price_unit": "each",
    "confidence": 0.92
}

Example 3:
INPUT: Product Name: Mild Steel Plate 10mm x 2400mm x 1200mm
       Description: Mild Steel Plate 10mm thick
       Price: 285.00 per sheet
OUTPUT: {
    "item_code": "PL-10-MS-2400x1200",
    "description": "10mm Mild Steel Plate 2400x1200mm",
    "metal_type": "mild_steel",
    "alloy": null,
    "specifics": "Hot rolled plate",
    "dimensions": "2400x1200x10mm",
    "unit_cost": 285.00,
    "price_unit": "per sheet",
    "confidence": 0.88
}

Example 4:
INPUT: Product Name: PVC Pipe 90mm x 6m
       Description: PVC Pipe 90mm diameter 6 metre length
       Price: 45.00 each
OUTPUT: {
    "item_code": "PIPE-90-PVC-6M",
    "description": "90mm PVC Pipe 6m length",
    "metal_type": null,
    "alloy": null,
    "specifics": "PVC pipe",
    "dimensions": "90mm diameter x 6m",
    "unit_cost": 45.00,
    "price_unit": "each",
    "confidence": 0.90
}
"""

    def _create_parsing_prompt(
        self, product_data_list: Dict[str, Any] | list[Dict[str, Any]]
    ) -> str:
        """Create LLM prompt for parsing product data (single item or batch)."""
        metal_types = [choice[0] for choice in MetalType.choices]

        # Convert single item to list for uniform processing
        if not isinstance(product_data_list, list):
            product_data_list = [product_data_list]

        training_examples = self._get_training_examples()

        prompt = f"""
Parse the following supplier product data and extract structured information for
inventory management.

{training_examples}

RULES:
- Be optimistic - make reasonable inferences from available data
- Standardize formats (dimensions, units, descriptions)
- If metal type is unclear, set to null rather than guessing
- Create meaningful item codes if none provided
- Keep descriptions concise but informative
- Ensure all dimensions follow consistent format
- Extract numeric price only (remove currency symbols, "from", etc.)
- Metal types must be one of: {", ".join(metal_types)} or null

OUTPUT FORMAT:
Return a JSON array with one object per input product. Each object should have
these fields:
{{
    "item_code": "Standardized item code for inventory",
    "description": "Clean, standardized description (max 255 chars)",
    "metal_type": "One of the valid metal types or null",
    "alloy": "Alloy specification or null",
    "specifics": "Specific details (max 255 chars)",
    "dimensions": "Standardized dimensions format or null",
    "unit_cost": "Numeric price value only",
    "price_unit": "Standardized unit",
    "confidence": "Your confidence (0.0 to 1.0)"
}}

INPUT DATA TO PARSE:
"""

        for i, product_data in enumerate(product_data_list, 1):
            prompt += f"""
Product {i}:
Product Name: {product_data.get("product_name", "N/A")}
Description: {product_data.get("description", "N/A")}
Specifications: {product_data.get("specifications", "N/A")}
Item Number: {product_data.get("item_no", "N/A")}
Variant Info: {product_data.get("variant_id", "N/A")}
Dimensions: {product_data.get("variant_width", "N/A")} x \
{product_data.get("variant_length", "N/A")}
Price: {product_data.get("variant_price", "N/A")} \
{product_data.get("price_unit", "N/A")}
"""

        return prompt

    def _call_llm(self, prompt: str) -> Dict[str, Any]:
        """Call LLM and parse response."""
        try:
            response = self.llm.completion(
                messages=[{"role": "user", "content": prompt}],
            )

            # Extract JSON from response
            response_text = response.choices[0].message.content.strip()

            # Try to find JSON array or object in the response
            start_idx = response_text.find("[")
            if start_idx == -1:
                start_idx = response_text.find("{")
            # Find the matching closing bracket/brace
            if response_text[start_idx] == "[":
                end_idx = response_text.rfind("]") + 1
            else:
                end_idx = response_text.rfind("}") + 1

            if start_idx == -1 or end_idx == 0:
                raise ValueError("No JSON found in LLM response")

            json_str = response_text[start_idx:end_idx]
            parsed_data = json.loads(json_str)

            # Ensure we always return a list for batch processing
            if not isinstance(parsed_data, list):
                parsed_data = [parsed_data]

            return {
                "parsed_data": parsed_data,
                "full_response": response_text,
                "success": True,
            }

        except Exception as e:
            logger.error(f"LLM parsing failed: {e}")
            return {"parsed_data": {}, "full_response": str(e), "success": False}

    def _save_mapping(
        self,
        input_hash: str,
        input_data: Dict[str, Any],
        parsed_data: Dict[str, Any],
        llm_response: Dict[str, Any],
    ) -> ProductParsingMapping:
        """Save parsing mapping to database."""

        # Convert Decimal values to strings for JSON serialization
        serializable_input = {}
        for key, value in input_data.items():
            if isinstance(value, Decimal):
                serializable_input[key] = str(value)
            else:
                serializable_input[key] = value

        # Convert confidence to Decimal if present
        confidence = parsed_data.get("confidence")
        if confidence is not None:
            try:
                confidence = Decimal(str(confidence))
            except (ValueError, TypeError):
                confidence = None

        # Convert unit_cost to Decimal if present
        unit_cost = parsed_data.get("unit_cost")
        if unit_cost is not None:
            try:
                unit_cost = Decimal(str(unit_cost))
            except (ValueError, TypeError):
                unit_cost = None

        # Use get_or_create to handle potential duplicates
        mapping, created = ProductParsingMapping.objects.get_or_create(
            input_hash=input_hash,
            defaults={
                "input_data": serializable_input,
                "mapped_item_code": parsed_data.get("item_code"),
                "mapped_description": parsed_data.get("description"),
                "mapped_metal_type": parsed_data.get("metal_type"),
                "mapped_alloy": parsed_data.get("alloy"),
                "mapped_specifics": parsed_data.get("specifics"),
                "mapped_dimensions": parsed_data.get("dimensions"),
                "mapped_unit_cost": unit_cost,
                "mapped_price_unit": parsed_data.get("price_unit"),
                "parser_version": self.PARSER_VERSION,
                "parser_confidence": confidence,
                "llm_response": llm_response,
            },
        )

        if not created:
            logger.info(
                f"Mapping already exists for hash {input_hash[:8]}... "
                f"(already processed)"
            )

        return mapping

    def parse_products_batch(
        self, product_data_list: list[Dict[str, Any]]
    ) -> list[ParsedProductResult]:
        """
        Parse multiple products in a single LLM call for efficiency.

        Args:
            product_data_list: List of raw supplier product data

        Returns:
            List of tuples (parsed_data_dict, was_cached)
        """
        if not product_data_list:
            return []

        # Group products by those that need parsing vs those already cached
        uncached_products = []
        uncached_indices = []
        results: list[ParsedProductResult | None] = [None] * len(product_data_list)

        for i, product_data in enumerate(product_data_list):
            input_hash = self._calculate_input_hash(product_data)
            existing_mapping = self._get_cached_mapping(input_hash)

            if existing_mapping:
                results[i] = (
                    {
                        "item_code": existing_mapping.mapped_item_code,
                        "description": existing_mapping.mapped_description,
                        "metal_type": existing_mapping.mapped_metal_type,
                        "alloy": existing_mapping.mapped_alloy,
                        "specifics": existing_mapping.mapped_specifics,
                        "dimensions": existing_mapping.mapped_dimensions,
                        "unit_cost": existing_mapping.mapped_unit_cost,
                        "price_unit": existing_mapping.mapped_price_unit,
                        "confidence": existing_mapping.parser_confidence,
                        "parser_version": existing_mapping.parser_version,
                    },
                    True,
                )
            else:
                uncached_products.append(product_data)
                uncached_indices.append(i)

        # Parse uncached products in batch
        if uncached_products:
            logger.info(f"Batch parsing {len(uncached_products)} products with LLM")
            prompt = self._create_parsing_prompt(uncached_products)
            llm_response = self._call_llm(prompt)

            if llm_response["success"] and len(llm_response["parsed_data"]) == len(
                uncached_products
            ):
                for j, parsed_data in enumerate(llm_response["parsed_data"]):
                    original_index = uncached_indices[j]
                    product_data = uncached_products[j]

                    # Save mapping
                    input_hash = self._calculate_input_hash(product_data)
                    mapping = self._save_mapping(
                        input_hash, product_data, parsed_data, llm_response
                    )

                    results[original_index] = (
                        {
                            "item_code": mapping.mapped_item_code,
                            "description": mapping.mapped_description,
                            "metal_type": mapping.mapped_metal_type,
                            "alloy": mapping.mapped_alloy,
                            "specifics": mapping.mapped_specifics,
                            "dimensions": mapping.mapped_dimensions,
                            "unit_cost": mapping.mapped_unit_cost,
                            "price_unit": mapping.mapped_price_unit,
                            "confidence": mapping.parser_confidence,
                            "parser_version": mapping.parser_version,
                        },
                        False,
                    )
            else:
                logger.error("Batch parsing failed or returned wrong number of results")
                # Fall back to individual parsing
                for j, product_data in enumerate(uncached_products):
                    original_index = uncached_indices[j]
                    results[original_index] = self.parse_product(product_data)

        return [result if result is not None else ({}, False) for result in results]

    def parse_product(
        self, product_data: Dict[str, Any]
    ) -> Tuple[Dict[str, Any], bool]:
        """
        Parse supplier product data to inventory format.

        Args:
            product_data: Raw supplier product data

        Returns:
            Tuple of (parsed_data_dict, was_cached)
        """
        # Calculate input hash based on description
        input_hash = self._calculate_input_hash(product_data)

        # Check for existing mapping
        existing_mapping = self._get_cached_mapping(input_hash)
        if existing_mapping:
            logger.info(f"Using cached mapping for hash {input_hash[:8]}...")
            return {
                "item_code": existing_mapping.mapped_item_code,
                "description": existing_mapping.mapped_description,
                "metal_type": existing_mapping.mapped_metal_type,
                "alloy": existing_mapping.mapped_alloy,
                "specifics": existing_mapping.mapped_specifics,
                "dimensions": existing_mapping.mapped_dimensions,
                "unit_cost": existing_mapping.mapped_unit_cost,
                "price_unit": existing_mapping.mapped_price_unit,
                "confidence": existing_mapping.parser_confidence,
                "parser_version": existing_mapping.parser_version,
            }, True

        # Parse with LLM
        logger.info(f"Parsing new product data with LLM (hash: {input_hash[:8]}...)")
        prompt = self._create_parsing_prompt([product_data])
        llm_response = self._call_llm(prompt)

        if not llm_response["success"] or not llm_response["parsed_data"]:
            logger.error(
                f"Failed to parse product data: {llm_response['full_response']}"
            )
            return {}, False

        # Get the first (and only) result from the batch
        parsed_data = llm_response["parsed_data"][0]

        # Save mapping for future use
        mapping = self._save_mapping(
            input_hash, product_data, parsed_data, llm_response
        )

        logger.info(f"Created new mapping for hash {input_hash[:8]}...")

        return {
            "item_code": mapping.mapped_item_code,
            "description": mapping.mapped_description,
            "metal_type": mapping.mapped_metal_type,
            "alloy": mapping.mapped_alloy,
            "specifics": mapping.mapped_specifics,
            "dimensions": mapping.mapped_dimensions,
            "unit_cost": mapping.mapped_unit_cost,
            "price_unit": mapping.mapped_price_unit,
            "confidence": mapping.parser_confidence,
            "parser_version": mapping.parser_version,
        }, False


def parse_supplier_product(product_data: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
    """
    Convenience function to parse a single supplier product.

    Args:
        product_data: Raw supplier product data

    Returns:
        Tuple of (parsed_data_dict, was_cached)
    """
    parser = ProductParser()
    return parser.parse_product(product_data)


def create_mapping_record(instance: SupplierProduct) -> None:
    """Create mapping record and set hash on SupplierProduct."""
    # Set mapping_hash on SupplierProduct
    mapping_hash = calculate_supplier_product_hash(instance)
    SupplierProduct.objects.filter(id=instance.id).update(mapping_hash=mapping_hash)

    # Create empty ProductParsingMapping record if it doesn't exist
    input_data = {
        "input_description": instance.description or instance.product_name or "",
        "input_product_name": instance.product_name or "",
        "input_specifications": instance.specifications or "",
    }

    ppm, created = ProductParsingMapping.objects.get_or_create(
        input_hash=mapping_hash,
        defaults={
            "input_data": json.dumps(input_data, indent=2),
            "created_at": timezone.now(),
        },
    )
    if created:
        logging.info(f"Created some shite:  {ppm}")
    else:
        logging.info(f"Updated some shite:  {ppm}")


def populate_all_mappings_with_llm() -> None:
    """Batch process all unpopulated ProductParsingMapping records with LLM."""
    # Find all unpopulated mappings
    unpopulated_mappings = ProductParsingMapping.objects.filter(
        mapped_item_code__isnull=True
    )

    if not unpopulated_mappings.exists():
        logger.info("No unpopulated mappings to process")
        return

    logger.info(
        f"Processing {unpopulated_mappings.count()} unpopulated mappings with LLM"
    )

    # Use existing batch processing
    parser = ProductParser()

    # Prepare product data for all mappings
    product_data_list: list[Dict[str, Any]] = []
    for mapping in unpopulated_mappings:
        input_data = mapping.input_data if isinstance(mapping.input_data, dict) else {}
        product_data = {
            "product_name": input_data.get("product_name")
            or input_data.get("input_product_name")
            or "",
            "description": input_data.get("description")
            or input_data.get("input_description")
            or "",
            "specifications": input_data.get("specifications")
            or input_data.get("input_specifications")
            or "",
        }
        product_data_list.append(product_data)

    # Batch process with LLM
    results = parser.parse_products_batch(product_data_list)

    # Update mappings and corresponding SupplierProducts
    for mapping, (parsed_data, was_cached) in zip(unpopulated_mappings, results):
        if parsed_data:
            # Update the mapping
            mapping.mapped_item_code = parsed_data.get("item_code")
            mapping.mapped_description = parsed_data.get("description")
            mapping.mapped_metal_type = parsed_data.get("metal_type")
            mapping.mapped_alloy = parsed_data.get("alloy")
            mapping.mapped_specifics = parsed_data.get("specifics")
            mapping.mapped_dimensions = parsed_data.get("dimensions")
            mapping.mapped_unit_cost = parsed_data.get("unit_cost")
            mapping.mapped_price_unit = parsed_data.get("price_unit")
            mapping.parser_confidence = parsed_data.get("confidence")
            mapping.parser_version = parsed_data.get("parser_version")
            mapping.save()

            # Update corresponding SupplierProducts via backflow
            SupplierProduct.objects.filter(mapping_hash=mapping.input_hash).update(
                parsed_item_code=parsed_data.get("item_code"),
                parsed_description=parsed_data.get("description"),
                parsed_metal_type=parsed_data.get("metal_type"),
                parsed_alloy=parsed_data.get("alloy"),
                parsed_specifics=parsed_data.get("specifics"),
                parsed_dimensions=parsed_data.get("dimensions"),
                parsed_unit_cost=parsed_data.get("unit_cost"),
                parsed_price_unit=parsed_data.get("price_unit"),
                parsed_at=timezone.now(),
                parser_version=parsed_data.get("parser_version"),
                parser_confidence=parsed_data.get("confidence"),
            )

            status = "from cache" if was_cached else "newly parsed"
            logger.info(f"Processed mapping {mapping.input_hash[:8]}... ({status})")

    logger.info(
        f"Completed batch processing of {unpopulated_mappings.count()} mappings"
    )
