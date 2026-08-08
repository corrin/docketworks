"""Field validation for data arriving from Xero.

A Xero record missing required fields is bad remote data, not a v2 defect —
``XeroValidationError`` carries enough identity (entity, xero_id, field names)
for the sync loop to persist it as a ``XeroError`` row and keep going, instead
of one malformed invoice aborting the whole entity sync.
"""

import json
import logging

logger = logging.getLogger(__name__)


class XeroValidationError(Exception):
    """A Xero object is missing required fields.

    Args:
        missing_fields: Names of the missing attributes.
        entity: The entity type, such as "invoice".
        xero_id: Identifier for the record in Xero.
    """

    def __init__(self, missing_fields: list[str], entity: str, xero_id: str | None) -> None:
        """Carry the record's identity so the error row can name it."""
        self.missing_fields = missing_fields
        self.entity = entity
        self.xero_id = xero_id
        super().__init__(f"Missing fields {missing_fields} for {entity} {xero_id}")


def validate_required_fields(
    fields: dict[str, object], entity: str, xero_id: str | None
) -> dict[str, object]:
    """Raise XeroValidationError if any value in ``fields`` is ``None``."""
    missing = [name for name, value in fields.items() if value is None]
    if missing:
        raw_json = fields.get("raw_json", {})
        logger.error(
            "Validation failed for %s %s: missing=%s\nraw_json=%s",
            entity,
            xero_id,
            missing,
            json.dumps(raw_json, indent=2, default=str),
        )
        raise XeroValidationError(missing, entity, xero_id)
    return fields
