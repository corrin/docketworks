import json
import logging
from decimal import Decimal, InvalidOperation

from apps.workflow.exceptions import XeroValidationError

logger = logging.getLogger("xero")


def to_decimal(value, *, field_label: str) -> Decimal:
    """Convert *value* to a non-negative ``Decimal``.

    Raises ``ValueError`` when *value* is not a valid decimal or is negative.
    """
    try:
        d = Decimal(str(value))
    except (InvalidOperation, TypeError):
        raise ValueError(f"Invalid decimal format for {field_label}.")
    if d < 0:
        raise ValueError(f"Negative value not allowed for {field_label}.")
    return d


def validate_required_fields(fields: dict, entity: str, xero_id):
    """Raise XeroValidationError if any value in ``fields`` is ``None``."""
    missing = [name for name, value in fields.items() if value is None]
    if missing:
        raw_json = fields.get("raw_json", {})
        logger.error(
            f"Validation failed for {entity} {xero_id}: "
            f"missing={missing}\nraw_json={json.dumps(raw_json, indent=2, default=str)}"
        )
        raise XeroValidationError(missing, entity, xero_id)
    return fields
