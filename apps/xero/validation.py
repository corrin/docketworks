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


def persist_xero_error(exc: XeroValidationError) -> None:
    """Create and save a ``XeroError`` row from the given validation failure.

    Lives here, not in apps/core/errors: XeroError is an apps.xero model and
    core sits below xero in the layer contract.
    """
    # Call-time import: this module loads before Django's app registry in
    # some tool contexts, and models cannot.
    from apps.xero.models import XeroError  # noqa: PLC0415

    XeroError.objects.create(
        message=str(exc),
        data={"missing_fields": exc.missing_fields},
        entity=exc.entity,
        reference_id=exc.xero_id or "",
        kind="Xero",
    )


def required[T](value: T | None, field: str, entity: str, xero_id: str) -> T:
    """Narrow a validated value for the type checker.

    ``validate_required_fields`` has already raised for None; this re-check
    is the mypy-visible witness, and a belt-and-braces guard if a call site
    ever reorders extraction before validation.
    """
    if value is None:
        raise XeroValidationError([field], entity, xero_id)
    return value


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
