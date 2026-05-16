"""
JSON schemas for mode-based quote generation.

Defines structured input/output contracts for CALC, PRICE, and TABLE modes
to ensure consistent data handling and validation.
"""

from typing import Any, Dict, List

CALC_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["inputs", "results", "questions"],
    "properties": {
        "inputs": {
            "type": "object",
            "properties": {
                "raw_input": {
                    "type": ["string", "null"],
                    "description": "The user's original input",
                },
                "parsed": {
                    "type": ["string", "null"],
                    "description": "What was extracted from the input as text",
                },
            },
        },
        "results": {
            "type": "object",
            "required": ["items", "assumptions"],
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["description", "quantity", "unit"],
                        "properties": {
                            "description": {
                                "type": "string",
                                "description": "What was calculated (e.g., 'Flat pattern', 'M10 bolts', 'Welding length')",
                            },
                            "quantity": {
                                "type": "number",
                                "description": "Calculated amount",
                            },
                            "unit": {
                                "type": "string",
                                "description": "Unit of measure (e.g., 'mm x mm', 'each', 'mm')",
                            },
                            "specs": {
                                "type": "string",
                                "description": "Additional specifications as text (e.g., 'material: 1.2mm steel, dimensions: 312mm')",
                            },
                        },
                    },
                },
                "assumptions": {
                    "type": "string",
                    "description": "Explicit assumptions made (ALWAYS provide - e.g., 'Assumed 3mm thickness, 304 stainless, open-top box')",
                },
            },
        },
        "questions": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Clarifying questions for missing/ambiguous data",
        },
    },
}

PRICE_SCHEMA = {
    "type": "object",
    "required": ["normalized", "candidates", "questions"],
    "properties": {
        "normalized": {
            "type": "object",
            "required": ["family", "grade", "thickness_mm", "form"],
            "properties": {
                "family": {
                    "type": "string",
                    "description": "Material family (e.g., stainless, aluminium)",
                },
                "grade": {
                    "type": "string",
                    "description": "Material grade (e.g., 304, 316, 5083)",
                },
                "thickness_mm": {
                    "type": "number",
                    "description": "Material thickness in mm",
                },
                "form": {
                    "type": "string",
                    "enum": ["sheet", "plate", "tube", "angle", "bar"],
                    "description": "Material form factor",
                },
                "sheet_size_mm": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 2,
                    "maxItems": 2,
                    "description": "Sheet dimensions if applicable",
                },
                "qty_uom": {
                    "type": "string",
                    "enum": ["sheet", "kg", "m", "each"],
                    "description": "Quantity unit of measure",
                },
                "qty_required": {"type": "number", "description": "Quantity needed"},
            },
        },
        "candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["supplier", "sku", "uom", "price_per_uom"],
                "properties": {
                    "supplier": {
                        "type": "string",
                        "description": "Supplier name or STOCK for inventory",
                    },
                    "sku": {
                        "type": "string",
                        "description": "Product SKU or stock code",
                    },
                    "uom": {
                        "type": "string",
                        "description": "Unit of measure for pricing",
                    },
                    "price_per_uom": {
                        "type": "number",
                        "minimum": 0,
                        "description": "Price per unit",
                    },
                    "lead_time_days": {
                        "type": "integer",
                        "minimum": 0,
                        "description": "Lead time in days",
                    },
                    "delivery": {
                        "type": "number",
                        "minimum": 0,
                        "description": "Delivery cost",
                    },
                    "notes": {
                        "type": "string",
                        "description": "Additional notes (finish, location, etc.)",
                    },
                },
            },
        },
        "questions": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 5,
            "description": "Clarifying questions for specifications",
        },
    },
}

TABLE_SCHEMA = {
    "type": "object",
    "required": ["rows", "totals", "markdown", "questions"],
    "properties": {
        "rows": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["item", "qty", "uom", "unit_cost", "subtotal"],
                "properties": {
                    "item": {"type": "string", "description": "Line item description"},
                    "qty": {"type": "number", "minimum": 0, "description": "Quantity"},
                    "uom": {"type": "string", "description": "Unit of measure"},
                    "unit_cost": {
                        "type": "number",
                        "minimum": 0,
                        "description": "Cost per unit",
                    },
                    "subtotal": {
                        "type": "number",
                        "minimum": 0,
                        "description": "Line total (qty × unit_cost)",
                    },
                    "notes": {
                        "type": "string",
                        "description": "Additional notes for this line",
                    },
                },
            },
            "description": "Quote line items",
        },
        "totals": {
            "type": "object",
            "required": [
                "material",
                "labour",
                "freight",
                "overheads",
                "markup_pct",
                "grand_total_ex_gst",
            ],
            "properties": {
                "material": {
                    "type": "number",
                    "minimum": 0,
                    "description": "Total material cost",
                },
                "labour": {
                    "type": "number",
                    "minimum": 0,
                    "description": "Total labour cost",
                },
                "freight": {
                    "type": "number",
                    "minimum": 0,
                    "description": "Total freight/delivery cost",
                },
                "overheads": {
                    "type": "number",
                    "minimum": 0,
                    "description": "Overhead costs",
                },
                "markup_pct": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 100,
                    "description": "Markup percentage",
                },
                "grand_total_ex_gst": {
                    "type": "number",
                    "minimum": 0,
                    "description": "Grand total excluding GST",
                },
            },
        },
        "markdown": {
            "type": "string",
            "description": "Formatted markdown table for display",
        },
        "questions": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 1,
            "description": "Final clarifications if needed",
        },
    },
}


def get_schema(mode: str) -> Dict[str, Any]:
    """
    Get the JSON schema for a specific mode.

    Args:
        mode: One of "CALC", "PRICE", or "TABLE"

    Returns:
        The corresponding JSON schema dictionary

    Raises:
        ValueError: If mode is not recognized
    """
    schemas = {"CALC": CALC_SCHEMA, "PRICE": PRICE_SCHEMA, "TABLE": TABLE_SCHEMA}

    if mode not in schemas:
        raise ValueError(f"Unknown mode: {mode}. Must be one of {list(schemas.keys())}")

    return schemas[mode]


def get_allowed_tools(mode: str) -> List[str]:
    """
    Get the list of allowed MCP tools for a specific mode.

    Args:
        mode: One of "CALC", "PRICE", or "TABLE"

    Returns:
        List of allowed tool names for the mode

    Raises:
        ValueError: If mode is not recognized
    """
    tools = {
        "CALC": ["calc_sheet_tenths", "emit_calc_result"],
        "PRICE": [
            "search_products",
            "get_pricing_for_material",
            "compare_suppliers",
            "emit_price_result",
        ],
        "TABLE": ["emit_table_result"],  # Only emit tool for structured output
    }

    if mode not in tools:
        raise ValueError(f"Unknown mode: {mode}. Must be one of {list(tools.keys())}")

    return tools[mode]
