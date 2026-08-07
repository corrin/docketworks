"""Generate golden vectors for the delta checksum from the Python canonicaliser.

The output JSON is the cross-language contract (ADR 0004): the Python side is
authoritative; the TypeScript port must reproduce every checksum exactly.
Each case carries `py_values` (tagged, reconstructed into rich Python types)
and `js_values` (the JSON the frontend would actually hold for the same state).

Run: uv run python -m scripts.generate.gen_delta_goldens
"""

import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from apps.job.services.delta_checksum import compute_job_delta_checksum
from scripts import REPO_ROOT

GOLDENS_PATH = REPO_ROOT / "tests" / "delta-checksum-goldens.json"

JOB_ID = "0f8fad5b-d9cb-469f-a165-70867728950e"


def _require_str(raw: object, kind: str) -> str:
    if not isinstance(raw, str):
        raise TypeError(f"{kind} vectors must tag their raw value as a string, got {type(raw)!r}")
    return raw


def _reconstruct(tagged: dict[str, Any]) -> object:
    kind, raw = tagged["kind"], tagged.get("raw")
    match kind:
        case "null":
            return None
        case "str" | "int" | "bool" | "list":
            return raw
        case "decimal":
            return Decimal(_require_str(raw, kind))
        case "date":
            return date.fromisoformat(_require_str(raw, kind))
        case "datetime":
            return datetime.fromisoformat(_require_str(raw, kind))
        case _:
            raise ValueError(f"Unknown kind: {kind}")


# Each case: name, fields as {field: {kind, raw}}, js_values as plain JSON the
# frontend holds for the same state (strings for decimals/dates, per the API).
CASES: list[dict[str, Any]] = [
    {
        "name": "single string",
        "fields": {"description": {"kind": "str", "raw": "Cut and fold"}},
        "js_values": {"description": "Cut and fold"},
    },
    {
        "name": "string needing trim",
        "fields": {"description": {"kind": "str", "raw": "  padded  "}},
        "js_values": {"description": "  padded  "},
    },
    {
        "name": "empty string stays empty (not null)",
        "fields": {"notes": {"kind": "str", "raw": ""}},
        "js_values": {"notes": ""},
    },
    {
        "name": "null value",
        "fields": {"order_number": {"kind": "null"}},
        "js_values": {"order_number": None},
    },
    {
        "name": "booleans",
        "fields": {
            "quoted": {"kind": "bool", "raw": True},
            "invoiced": {"kind": "bool", "raw": False},
        },
        "js_values": {"quoted": True, "invoiced": False},
    },
    {
        "name": "integer",
        "fields": {"priority": {"kind": "int", "raw": 42}},
        "js_values": {"priority": 42},
    },
    # SHARP EDGE (inherited from v1): the server checksums model Decimals, which
    # normalise away trailing zeros ('105.50' -> '105.5'), but the TS side does
    # NOT normalise numeric *strings*. The protocol therefore only agrees when
    # the client passes numbers, not the API's decimal strings. v2 client code
    # must keep numeric form state as JS numbers before checksumming.
    {
        "name": "decimal with trailing zeros normalises (client must hold number)",
        "fields": {"charge_out_rate": {"kind": "decimal", "raw": "105.50"}},
        "js_values": {"charge_out_rate": 105.5},
    },
    {
        "name": "decimal integer-valued (client must hold number)",
        "fields": {"quote_total": {"kind": "decimal", "raw": "1200.00"}},
        "js_values": {"quote_total": 1200},
    },
    {
        "name": "date",
        "fields": {"delivery_date": {"kind": "date", "raw": "2026-03-15"}},
        "js_values": {"delivery_date": "2026-03-15"},
    },
    {
        "name": "aware datetime normalises to UTC milliseconds Z",
        "fields": {"created_at": {"kind": "datetime", "raw": "2026-03-15T14:30:45.123000+13:00"}},
        "js_values": {"created_at": "2026-03-15T14:30:45.123+13:00"},
    },
    {
        "name": "multiple fields sort alphabetically",
        "fields": {
            "name": {"kind": "str", "raw": "Handrail"},
            "description": {"kind": "str", "raw": "SS 316 handrail"},
            "order_number": {"kind": "str", "raw": "PO-123"},
        },
        "js_values": {
            "name": "Handrail",
            "description": "SS 316 handrail",
            "order_number": "PO-123",
        },
    },
    {
        "name": "list of strings",
        "fields": {"tags": {"kind": "list", "raw": ["urgent", "welding"]}},
        "js_values": {"tags": ["urgent", "welding"]},
    },
    {
        "name": "unicode content",
        "fields": {"description": {"kind": "str", "raw": "Māori café — 5m × 3m"}},  # noqa: RUF001 -- multiplication sign is the point of this unicode vector
        "js_values": {"description": "Māori café — 5m × 3m"},  # noqa: RUF001 -- same
    },
    {
        "name": "pipe and equals characters in value",
        "fields": {"notes": {"kind": "str", "raw": "a=b|c=d"}},
        "js_values": {"notes": "a=b|c=d"},
    },
]


def main() -> None:
    vectors = []
    for case in CASES:
        py_values = {field: _reconstruct(tag) for field, tag in case["fields"].items()}
        checksum = compute_job_delta_checksum(JOB_ID, py_values)
        vectors.append(
            {
                "name": case["name"],
                "job_id": JOB_ID,
                "fields": case["fields"],
                "js_values": case["js_values"],
                "checksum": checksum,
            }
        )
    GOLDENS_PATH.parent.mkdir(parents=True, exist_ok=True)
    GOLDENS_PATH.write_text(json.dumps(vectors, indent=2, ensure_ascii=False) + "\n")
    print(f"Wrote {len(vectors)} golden vectors to {GOLDENS_PATH}")


if __name__ == "__main__":
    main()
