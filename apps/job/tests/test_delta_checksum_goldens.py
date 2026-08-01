"""The golden vectors are the cross-language checksum contract (ADR 0004).

If this test fails, the canonicalisation changed — that silently rejects every
in-flight frontend save. Regenerate goldens ONLY for an intentional, versioned
protocol change, never to make a refactor pass.
"""

import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from apps.job.services.delta_checksum import compute_job_delta_checksum

GOLDENS = json.loads(
    (Path(__file__).resolve().parents[3] / "tests" / "delta-checksum-goldens.json").read_text()
)


def _reconstruct(tagged: dict[str, Any]) -> object:
    kind, raw = tagged["kind"], tagged.get("raw")
    match kind:
        case "null":
            return None
        case "str" | "int" | "bool" | "list":
            return raw
        case "decimal":
            assert isinstance(raw, str)
            return Decimal(raw)
        case "date":
            assert isinstance(raw, str)
            return date.fromisoformat(raw)
        case "datetime":
            assert isinstance(raw, str)
            return datetime.fromisoformat(raw)
        case _:
            raise ValueError(f"Unknown kind: {kind}")


@pytest.mark.parametrize("vector", GOLDENS, ids=[v["name"] for v in GOLDENS])
def test_checksum_matches_golden(vector: dict[str, Any]) -> None:
    values = {field: _reconstruct(tag) for field, tag in vector["fields"].items()}
    assert compute_job_delta_checksum(vector["job_id"], values) == vector["checksum"]
