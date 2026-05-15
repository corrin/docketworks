import logging
import re
from decimal import Decimal
from typing import Any

from django.utils import timezone

from apps.job.enums import MetalType
from apps.purchasing.models import Stock
from apps.quoting.services.product_parser import ProductParser
from apps.workflow.exceptions import AlreadyLoggedException
from apps.workflow.services.error_persistence import persist_app_error

logger = logging.getLogger(__name__)

METAL_TYPE_ALIASES = {
    "aluminium": MetalType.ALUMINIUM,
    "stainless steel": MetalType.STAINLESS_STEEL,
    "stainless_steel": MetalType.STAINLESS_STEEL,
    "mild steel": MetalType.MILD_STEEL,
    "mild_steel": MetalType.MILD_STEEL,
    "galvanised": MetalType.GALVANIZED,
    "galvanized": MetalType.GALVANIZED,
}

GENERIC_SPECIFICS = {
    "service item",
    "testing stock",
}


def _compact_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _normalise_metal_type(value: Any) -> str | None:
    if not isinstance(value, str):
        return None

    raw_value = value.strip().lower()
    if not raw_value:
        return None

    valid_values = {choice[0] for choice in MetalType.choices}
    if raw_value in valid_values:
        return raw_value

    alias_key = raw_value.replace("-", " ").replace("_", " ")
    return METAL_TYPE_ALIASES.get(alias_key)


def _normalise_alloy(value: Any, stock_instance: Stock) -> str | None:
    if not isinstance(value, str):
        return None

    alloy = value.strip().upper()
    if not alloy:
        return None

    source_text = " ".join(
        [
            stock_instance.description or "",
            stock_instance.item_code or "",
            stock_instance.specifics or "",
        ]
    )
    if _compact_text(alloy) in _compact_text(source_text):
        return alloy
    else:
        return None


def _normalise_specifics(value: Any, has_material_context: bool) -> str | None:
    if not has_material_context or not isinstance(value, str):
        return None

    specifics = value.strip()
    if not specifics or len(specifics) > 255:
        return None

    if specifics.lower() in GENERIC_SPECIFICS:
        return None
    else:
        return specifics


def _normalise_confidence(value: Any) -> Decimal | None:
    if value is None:
        return None

    try:
        return Decimal(str(value))
    except (ArithmeticError, TypeError, ValueError):
        return None


def auto_parse_stock_item(stock_instance: Stock, *, force: bool = False) -> None:
    """
    Parse Stock items to extract metal_type, alloy, and specifics from description.
    Call this explicitly when creating new stock items that need parsing.
    """
    # Skip if already parsed
    if stock_instance.parsed_at and not force:
        return

    try:
        attempted_at = timezone.now()
        # Prepare stock data for parsing - use description as main input
        stock_data = {
            "product_name": stock_instance.description or "",
            "description": stock_instance.description or "",
            "specifications": stock_instance.specifics or "",
            "item_no": stock_instance.item_code or "",
            "variant_id": f"stock-{stock_instance.id}",  # Unique identifier
            "variant_width": "",
            "variant_length": "",
            "variant_price": stock_instance.unit_cost,
            "price_unit": "each",  # Default for stock items
        }

        # Parse the stock item
        parser = ProductParser()
        Stock.objects.filter(id=stock_instance.id).update(
            parser_attempted_at=attempted_at
        )
        parsed_data, was_cached = parser.parse_product(stock_data)

        if parsed_data:
            # Only update fields that are currently blank/unspecified
            updates = {
                "parser_attempted_at": attempted_at,
                "parser_version": parsed_data.get("parser_version"),
                "parser_confidence": _normalise_confidence(
                    parsed_data.get("confidence")
                ),
            }
            accepted_metadata_fields: list[str] = []
            parsed_metal_type = _normalise_metal_type(parsed_data.get("metal_type"))
            parsed_alloy = _normalise_alloy(parsed_data.get("alloy"), stock_instance)

            if (
                not stock_instance.metal_type
                or stock_instance.metal_type == "unspecified"
            ):
                if parsed_metal_type:
                    updates["metal_type"] = parsed_metal_type
                    accepted_metadata_fields.append("metal_type")
                else:
                    pass  # Gemini returned no valid metal type for this stock row.
            else:
                pass  # Existing metal type wins over parser output.

            if not stock_instance.alloy:
                if parsed_alloy:
                    updates["alloy"] = parsed_alloy
                    accepted_metadata_fields.append("alloy")
                else:
                    pass  # Avoid saving alloys not present in the stock source text.
            else:
                pass  # Existing alloy wins over parser output.

            if not stock_instance.specifics:
                has_existing_metal_type = bool(
                    stock_instance.metal_type
                    and stock_instance.metal_type != "unspecified"
                )
                has_material_context = bool(
                    stock_instance.alloy
                    or has_existing_metal_type
                    or parsed_metal_type
                    or parsed_alloy
                )
                parsed_specifics = _normalise_specifics(
                    parsed_data.get("specifics"),
                    has_material_context,
                )
                if parsed_specifics:
                    updates["specifics"] = parsed_specifics
                    accepted_metadata_fields.append("specifics")
                else:
                    pass  # Specifics without material context are too noisy for stock.
            else:
                pass  # Existing specifics wins over parser output.

            if accepted_metadata_fields:
                updates["parsed_at"] = attempted_at
            else:
                pass  # Attempt recorded; no accepted stock metadata was found.

            Stock.objects.filter(id=stock_instance.id).update(**updates)

            status = "from cache" if was_cached else "newly parsed"
            logger.info(
                "Parsed stock item %s (%s): %s",
                stock_instance.id,
                status,
                accepted_metadata_fields,
            )
        else:
            logger.warning("Failed to parse stock item %s", stock_instance.id)

    except AlreadyLoggedException:
        raise
    except Exception as exc:
        logger.exception("Error parsing stock item %s: %s", stock_instance.id, exc)
        err = persist_app_error(exc)
        raise AlreadyLoggedException(exc, err.id) from exc
