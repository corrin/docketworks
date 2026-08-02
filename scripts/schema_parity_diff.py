"""Compare v2's live OpenAPI surface against v1's frozen contract (schema.yml).

The plan's standing API-parity instrument. Three categories:

- DRIFT (fails, exit 1): an operation exists at the same path+method in both
  schemas but with a different operationId, or v2 exposes an operation v1
  never had that is not covered by the parity ledger
  (docs/accepted-api-differences.yml, matched on the ledger's `operation`).
- NOT YET PORTED (informational): v1 operations absent from v2 — expected
  while the rewrite is in flight; printed as a count with per-prefix detail.
- MATCHED: path+method+operationId agree.

A ratcheting baseline (scripts/schema-parity-baseline.txt) records every
operationId that has ever matched: once ported, an operation disappearing
from v2 is DRIFT, not "not yet ported" — deleting an endpoint requires a
deliberate baseline regeneration. Run with --update-baseline after adding
operations; CI verifies the committed baseline is current.

Usage: uv run python scripts/schema_parity_diff.py [--update-baseline]
Exit 0 = no unexplained drift and baseline current.
"""

import os
import re
import sys
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings_test")

V1_SCHEMA = REPO / "frontend" / "schema.yml"
LEDGER = REPO / "docs" / "accepted-api-differences.yml"
BASELINE = REPO / "scripts" / "schema-parity-baseline.txt"

METHODS = ("get", "post", "put", "patch", "delete")

Operations = dict[tuple[str, str], str]  # (path, method) -> operationId


def _operations(spec: dict[str, Any]) -> Operations:
    ops: Operations = {}
    for path, item in spec.get("paths", {}).items():
        if not isinstance(item, dict):
            raise TypeError(f"Malformed path item at {path!r}")
        # Path *parameter names* are template labels, not wire contract:
        # /x/{id}/ and /x/{call_id}/ serve identical URLs. Normalise so the
        # diff guards the actual HTTP surface (v2 uses descriptive names).
        wire_path = re.sub(r"\{[^}]+\}", "{}", path)
        for method in METHODS:
            operation = item.get(method)
            if operation is None:
                continue
            ops[(wire_path, method)] = str(operation.get("operationId", ""))
    return ops


def _v1_operations() -> Operations:
    with V1_SCHEMA.open() as fh:
        return _operations(yaml.safe_load(fh))


def _v2_operations() -> Operations:
    import django

    django.setup()
    from config.api import api

    spec = api.get_openapi_schema(path_prefix="/api")
    return _operations(dict(spec))


def _ledgered_operations() -> set[str]:
    with LEDGER.open() as fh:
        entries = yaml.safe_load(fh) or []
    ops = set()
    for entry in entries:
        operation = entry.get("operation")
        if not operation:
            raise ValueError(f"Ledger entry without an operation field: {entry!r}")
        ops.add(str(operation))
    return ops


def _baseline() -> set[str]:
    if not BASELINE.exists():
        return set()
    return {
        line.strip()
        for line in BASELINE.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    }


def _classify(v1: Operations, v2: Operations, ledgered: set[str]) -> tuple[list[str], set[str]]:
    """Return (drift lines, operationIds that matched the contract)."""
    drift: list[str] = []
    matched_ops: set[str] = set()
    for key, v2_op in sorted(v2.items()):
        path, method = key
        if key in v1:
            if v1[key] == v2_op:
                matched_ops.add(v2_op)
            else:
                drift.append(
                    f"operationId mismatch at {method.upper()} {path}: v1={v1[key]!r} v2={v2_op!r}"
                )
        elif v2_op in ledgered:
            matched_ops.add(v2_op)
        else:
            drift.append(
                f"v2-only operation not in parity ledger: {method.upper()} {path} ({v2_op})"
            )
    return drift, matched_ops


def _apply_baseline_ratchet(
    matched_ops: set[str], baseline: set[str], update_baseline: bool
) -> list[str]:
    """Regression ratchet: an operation that ever matched may not vanish."""
    drift = [
        f"previously-ported operation missing from v2: {regressed} "
        "(regression, or a deliberate removal needing a baseline regeneration)"
        for regressed in sorted(baseline - matched_ops)
    ]
    if update_baseline:
        merged = sorted(baseline | matched_ops)
        BASELINE.write_text(
            "# Ratchet: every operationId that has ever matched the v1 contract.\n"
            "# Grows via --update-baseline; shrinking it is a deliberate act.\n"
            + "\n".join(merged)
            + "\n"
        )
        print(f"baseline updated: {len(merged)} operations")
    elif matched_ops - baseline:
        drift.append(
            f"{len(matched_ops - baseline)} newly-matched operations not in the baseline "
            "— run with --update-baseline and commit the file"
        )
    return drift


def main() -> int:
    v1 = _v1_operations()
    v2 = _v2_operations()

    drift, matched_ops = _classify(v1, v2, _ledgered_operations())
    drift += _apply_baseline_ratchet(matched_ops, _baseline(), "--update-baseline" in sys.argv)

    unported = sorted(set(v1) - set(v2))
    by_prefix: dict[str, int] = {}
    for path, _method in unported:
        prefix = "/".join(path.split("/")[:3]) or path
        by_prefix[prefix] = by_prefix.get(prefix, 0) + 1

    print(f"matched: {len(matched_ops)}   v1-not-yet-ported: {len(unported)}   drift: {len(drift)}")
    for prefix, count in sorted(by_prefix.items()):
        print(f"  not yet ported under {prefix}: {count}")
    if drift:
        print("\nDRIFT (fix the API or add a reasoned parity-ledger entry):")
        for line in drift:
            print(f"  {line}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
