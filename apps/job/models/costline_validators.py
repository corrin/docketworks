from __future__ import annotations

from typing import Any, Mapping

import jsonschema
from django.core.exceptions import ValidationError

# Common schema fragments used across meta and ext_refs validation.
STRING_OR_NULL = {"type": ["string", "null"]}
NUMBER_OR_NULL = {"type": ["number", "integer", "null"]}
BOOLEAN_OR_NULL = {"type": ["boolean", "null"]}


def _validate_mapping(
    value: Mapping[str, Any] | None, field_label: str
) -> Mapping[str, Any]:
    """Ensure the JSONField value is a mapping before schema validation."""
    if not value:
        return {}
    if isinstance(value, Mapping):
        return value
    raise ValidationError({field_label: "Value must be a JSON object."}, code="invalid")


def _run_schema_validation(
    value: Mapping[str, Any], schema: dict[str, Any], field_label: str
) -> None:
    """Run jsonschema validation and surface readable ValidationError messages."""
    try:
        jsonschema.validate(instance=value, schema=schema)
    except (
        jsonschema.ValidationError
    ) as exc:  # pragma: no cover - exercised indirectly in tests
        raise ValidationError(
            {
                field_label: f"{exc.message} (path: {'/'.join(map(str, exc.path)) or '.'})"
            },
            code="invalid",
        ) from exc


TIME_META_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "staff_id": STRING_OR_NULL,
        "date": STRING_OR_NULL,
        "is_billable": BOOLEAN_OR_NULL,
        "start_time": STRING_OR_NULL,
        "end_time": STRING_OR_NULL,
        "wage_rate_multiplier": NUMBER_OR_NULL,
        "bill_rate_multiplier": NUMBER_OR_NULL,
        "note": STRING_OR_NULL,
        "created_from_timesheet": BOOLEAN_OR_NULL,
        "wage_rate": NUMBER_OR_NULL,
        "charge_out_rate": NUMBER_OR_NULL,
        "labour_minutes": NUMBER_OR_NULL,
        "consumed_by": STRING_OR_NULL,
        "comments": STRING_OR_NULL,
        "source": STRING_OR_NULL,
    },
    "additionalProperties": False,
}

MATERIAL_META_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "item_code": STRING_OR_NULL,
        "comments": STRING_OR_NULL,
        "source": STRING_OR_NULL,
        "retail_rate": NUMBER_OR_NULL,
        "po_number": STRING_OR_NULL,
        "consumed_by": STRING_OR_NULL,
    },
    "additionalProperties": False,
}

ADJUSTMENT_META_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "comments": STRING_OR_NULL,
        "source": STRING_OR_NULL,
    },
    "additionalProperties": False,
}

GENERIC_META_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "additionalProperties": False,
}

COSTLINE_META_SCHEMAS: dict[str, dict[str, Any]] = {
    "time": TIME_META_SCHEMA,
    "material": MATERIAL_META_SCHEMA,
    "adjust": ADJUSTMENT_META_SCHEMA,
}

COSTLINE_EXTREFS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "time_entry_id": STRING_OR_NULL,
        "material_entry_id": STRING_OR_NULL,
        "adjustment_entry_id": STRING_OR_NULL,
        "stock_id": STRING_OR_NULL,
        "purchase_order_id": STRING_OR_NULL,
        "purchase_order_line_id": STRING_OR_NULL,
        "source_row": STRING_OR_NULL,
        "source_sheet": STRING_OR_NULL,
        "staff_id": STRING_OR_NULL,
    },
    "additionalProperties": False,
}


def validate_costline_meta(meta: Mapping[str, Any] | None, kind: str) -> None:
    """Validate CostLine.meta against a JSON schema based on the line kind."""
    meta_dict = _validate_mapping(meta, "meta")
    schema = COSTLINE_META_SCHEMAS.get(kind, GENERIC_META_SCHEMA)
    _run_schema_validation(meta_dict, schema, "meta")


def validate_costline_ext_refs(ext_refs: Mapping[str, Any] | None) -> None:
    """Validate CostLine.ext_refs structure."""
    ext_refs_dict = _validate_mapping(ext_refs, "ext_refs")
    _run_schema_validation(ext_refs_dict, COSTLINE_EXTREFS_SCHEMA, "ext_refs")
