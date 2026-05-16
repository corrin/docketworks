"""Common utilities for AI price extraction providers."""

import logging

logger = logging.getLogger(__name__)


def create_extraction_prompt() -> str:
    """Generates a comprehensive prompt for supplier price list data extraction."""
    return """Extract supplier price list data from this document and return it in the following JSON format:
    {
    "supplier": {
    "name": "Supplier Name",
    "customer": "Customer name if shown",
    "date": "Date if shown (YYYY-MM-DD format)"
    },
    "items": [
    {
    "description": "EXACT raw text description from price list",
    "unit_price": "123.45",
    "supplier_item_code": "Item code/SKU if available",
    "variant_id": "Unique identifier for this specific variant",
    "metal_type": "Steel, Aluminium, Galvanised Steel, Stainless Steel, etc.",
    "dimensions": "Dimensions as shown",
    "specifications": "Technical specs like alloy, temper, finish"
    }
    ]
    }
"""


def clean_json_response(text: str) -> str:
    """Clean up JSON response by removing markdown code blocks."""
    text = text.strip()

    if "```json" in text:
        text = text.split("```json")[1]
        if "```" in text:
            text = text.split("```")[0]
    elif "```" in text:
        text = text.replace("```", "")

    return text.strip()


def log_token_usage(usage, api_name):
    """Log token usage from AI API response."""
    if hasattr(usage, "input_tokens"):
        input_tokens = usage.input_tokens
        output_tokens = usage.output_tokens
    elif hasattr(usage, "prompt_tokens"):
        input_tokens = usage.prompt_tokens
        output_tokens = usage.completion_tokens
    elif isinstance(usage, dict):
        input_tokens = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0)
    else:
        input_tokens = 0
        output_tokens = 0

    total_tokens = input_tokens + output_tokens

    logger.info(
        f"{api_name} API token usage for price list extraction: "
        f"Input: {input_tokens}, Output: {output_tokens}, Total: {total_tokens}"
    )
