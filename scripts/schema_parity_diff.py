"""Compare v2's live OpenAPI surface against v1's frozen contract (schema.yml).

The plan's standing API-parity instrument. Three categories:

- DRIFT (fails, exit 1): an operation exists at the same path+method in both
  schemas but with a different operationId, or v2 exposes an operation v1
  never had that is not covered by the parity ledger
  (docs/accepted-api-differences.yml, matched on the ledger's `operation`).
- NOT YET PORTED (informational): v1 operations absent from v2 — expected
  while the rewrite is in flight; printed as a count with per-prefix detail.
- MATCHED: path+method+operationId agree.
- UUID GAPS: an operation in both schemas where v1 declares
  `type: string, format: uuid` on a property and v2 declares a bare string.
  DRF emitted that format automatically from every UUIDField; v2's ported
  Ninja schemas annotate the same fields `str`, so the contract is weaker.
  The known set lives in scripts/schema-uuid-gaps.txt and the live set must
  EQUAL it: a new gap fails (that is the accumulation this exists to stop),
  and a gap that has been fixed without updating the file fails too, so the
  file cannot rot into a wishlist. It ratchets DOWN to zero.

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
UUID_GAPS = REPO / "scripts" / "schema-uuid-gaps.txt"

METHODS = ("get", "post", "put", "patch", "delete")

Operations = dict[tuple[str, str], str]  # (path, method) -> operationId
OperationSpecs = dict[tuple[str, str], dict[str, Any]]  # (path, method) -> operation object


def _wire_path(path: str) -> str:
    """Path with parameter names blanked: /x/{id}/ and /x/{call_id}/ are one URL."""
    return re.sub(r"\{[^}]+\}", "{}", path)


def _operations(spec: dict[str, Any]) -> Operations:
    ops: Operations = {}
    for path, item in spec.get("paths", {}).items():
        if not isinstance(item, dict):
            raise TypeError(f"Malformed path item at {path!r}")
        # Path *parameter names* are template labels, not wire contract:
        # /x/{id}/ and /x/{call_id}/ serve identical URLs. Normalise so the
        # diff guards the actual HTTP surface (v2 uses descriptive names).
        wire_path = _wire_path(path)
        for method in METHODS:
            operation = item.get(method)
            if operation is None:
                continue
            ops[(wire_path, method)] = str(operation.get("operationId", ""))
    return ops


def _v1_spec() -> dict[str, Any]:
    with V1_SCHEMA.open() as fh:
        return dict(yaml.safe_load(fh))


def _v2_spec() -> dict[str, Any]:
    import django

    django.setup()
    from config.api import api

    return dict(api.get_openapi_schema(path_prefix="/api"))


def _operation_specs(spec: dict[str, Any]) -> OperationSpecs:
    """(wire path, method) -> the operation object, with path-level params merged in."""
    specs: OperationSpecs = {}
    for path, item in spec.get("paths", {}).items():
        shared_params = item.get("parameters") or []
        for method in METHODS:
            operation = item.get(method)
            if operation is None:
                continue
            merged = dict(operation)
            merged["parameters"] = list(shared_params) + list(operation.get("parameters") or [])
            specs[(_wire_path(path), method)] = merged
    return specs


def _deref(spec: dict[str, Any], node: Any, seen: tuple[str, ...] = ()) -> dict[str, Any]:
    """Follow $ref chains. Returns {} on a cycle rather than recursing forever."""
    while isinstance(node, dict) and "$ref" in node:
        ref = str(node["$ref"])
        if ref in seen:
            return {}
        seen += (ref,)
        cursor: Any = spec
        for part in ref.lstrip("#/").split("/"):
            cursor = cursor.get(part, {}) if isinstance(cursor, dict) else {}
        node = cursor
    return node if isinstance(node, dict) else {}


def _walk_properties(
    spec: dict[str, Any],
    node: Any,
    prefix: tuple[str, ...] = (),
    seen_nodes: frozenset[int] = frozenset(),
    out: dict[tuple[str, ...], dict[str, Any]] | None = None,
) -> dict[tuple[str, ...], dict[str, Any]]:
    """Every property under `node`, keyed by its path WITHIN the operation.

    Keyed by property path, never by component name: DRF and Ninja name their
    components differently and the name is not contract. Recursion is bounded
    by node identity, because these schemas contain cycles (a Job carries
    events that carry a job).
    """
    out = {} if out is None else out
    resolved = _deref(spec, node)
    if not resolved or id(resolved) in seen_nodes:
        return out
    seen_nodes = seen_nodes | {id(resolved)}

    for name, raw in (resolved.get("properties") or {}).items():
        child = _deref(spec, raw)
        out.setdefault((*prefix, str(name)), child)
        _walk_properties(spec, child, (*prefix, str(name)), seen_nodes, out)
    if "items" in resolved:
        _walk_properties(spec, resolved["items"], (*prefix, "[]"), seen_nodes, out)
    for combinator in ("allOf", "oneOf", "anyOf"):
        for branch in resolved.get(combinator) or []:
            _walk_properties(spec, branch, prefix, seen_nodes, out)
    return out


def _body_properties(
    spec: dict[str, Any], operation: dict[str, Any]
) -> dict[tuple[str, ...], dict[str, Any]]:
    """Request and response properties, namespaced so a body cannot mask a response."""
    found: dict[tuple[str, ...], dict[str, Any]] = {}
    body = _deref(spec, operation.get("requestBody") or {})
    for media in (body.get("content") or {}).values():
        for path, node in _walk_properties(spec, (media or {}).get("schema") or {}).items():
            found.setdefault(("request", *path), node)
    for code, response in (operation.get("responses") or {}).items():
        resolved = _deref(spec, response)
        for media in (resolved.get("content") or {}).values():
            for path, node in _walk_properties(spec, (media or {}).get("schema") or {}).items():
                found.setdefault((f"response:{code}", *path), node)
    return found


def _parameters(
    spec: dict[str, Any], operation: dict[str, Any]
) -> dict[tuple[str, ...], dict[str, Any]]:
    """Parameter schemas, keyed so both schemas agree on what matches what.

    Query parameter names ARE contract, so they key by name. PATH parameter
    names are template labels — v1's `{id}` is v2's `{job_id}` for the same
    URL — so they key by position. 15 of v1's 102 uuid path parameters are
    renamed in v2 and would be silently skipped by a name match.
    """
    found: dict[tuple[str, ...], dict[str, Any]] = {}
    position = 0
    for raw in operation.get("parameters") or []:
        parameter = _deref(spec, raw)
        schema = _deref(spec, parameter.get("schema") or {})
        location = parameter.get("in")
        if location == "path":
            found.setdefault(("path-param", str(position)), schema)
            position += 1
        elif location == "query":
            found.setdefault(("query-param", str(parameter.get("name"))), schema)
    return found


def _is_uuid(spec: dict[str, Any], node: dict[str, Any], depth: int = 0) -> bool:
    """Whether this property declares a uuid, through nullable unions.

    The two schemas spell "nullable uuid" differently and neither is wrong:
    v1 is OpenAPI 3.0 from DRF (`type: string, format: uuid, nullable: true`),
    v2 is 3.1 from Ninja (`anyOf: [{type: string, format: uuid}, {type: null}]`).
    Reading only the top level would report every optional identifier in v2 as
    a regression when it is nothing of the sort.
    """
    if depth > 8:  # union nesting is shallow; this only bounds pathological input
        return False
    resolved = _deref(spec, node)
    if resolved.get("format") == "uuid":
        return True
    for combinator in ("anyOf", "oneOf", "allOf"):
        for branch in resolved.get(combinator) or []:
            if _is_uuid(spec, branch, depth + 1):
                return True
    return False


def _uuid_gaps(v1_spec: dict[str, Any], v2_spec: dict[str, Any]) -> set[str]:
    """Properties v1 declares as uuid that v2, for the same operation, does not.

    A property v1 has and v2 does not expose at all is NOT a gap: that is an
    operation-shape difference, which the ledger already governs.
    """
    v1_ops, v2_ops = _operation_specs(v1_spec), _operation_specs(v2_spec)
    gaps: set[str] = set()
    for key in sorted(set(v1_ops) & set(v2_ops)):
        path, method = key
        v1_props = {**_body_properties(v1_spec, v1_ops[key]), **_parameters(v1_spec, v1_ops[key])}
        v2_props = {**_body_properties(v2_spec, v2_ops[key]), **_parameters(v2_spec, v2_ops[key])}
        for prop_path, v1_node in v1_props.items():
            if not _is_uuid(v1_spec, v1_node):
                continue
            v2_node = v2_props.get(prop_path)
            if v2_node is None or _is_uuid(v2_spec, v2_node):
                continue
            gaps.add(f"{method.upper()} {path} :: {'.'.join(prop_path)}")
    return gaps


def _recorded_uuid_gaps() -> set[str]:
    if not UUID_GAPS.exists():
        return set()
    return {
        line.strip()
        for line in UUID_GAPS.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    }


def _apply_uuid_ratchet(live: set[str], recorded: set[str], update: bool) -> list[str]:
    """The live gap set must EQUAL the recorded one, in both directions."""
    if update:
        UUID_GAPS.write_text(
            "# Properties v1 declares `format: uuid` that v2 declares as a bare string.\n"
            "# DRF emitted the format from every UUIDField; v2's ported schemas say `str`.\n"
            "#\n"
            "# This list may only SHRINK. A gap missing from it fails (a new regression);\n"
            "# a listed gap that no longer exists also fails, so the file cannot rot into\n"
            "# a wishlist. Regenerate with --update-baseline when you fix one.\n"
            "#\n"
            "# Fixing these is the str -> UUID sweep, which changes runtime validation\n"
            "# (a non-UUID string starts returning 422) and is therefore post-cutover.\n"
            + "\n".join(sorted(live))
            + "\n"
        )
        print(f"uuid gaps recorded: {len(live)}")
        return []

    drift = [
        f"NEW uuid contract regression (v1 declares format: uuid, v2 does not): {gap}"
        for gap in sorted(live - recorded)
    ]
    drift += [
        f"uuid gap recorded but no longer present — regenerate the file: {gap}"
        for gap in sorted(recorded - live)
    ]
    return drift


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
    update_baseline = "--update-baseline" in sys.argv
    v1_spec, v2_spec = _v1_spec(), _v2_spec()
    v1, v2 = _operations(v1_spec), _operations(v2_spec)

    drift, matched_ops = _classify(v1, v2, _ledgered_operations())
    drift += _apply_baseline_ratchet(matched_ops, _baseline(), update_baseline)

    live_gaps = _uuid_gaps(v1_spec, v2_spec)
    drift += _apply_uuid_ratchet(live_gaps, _recorded_uuid_gaps(), update_baseline)

    unported = sorted(set(v1) - set(v2))
    by_prefix: dict[str, int] = {}
    for path, _method in unported:
        prefix = "/".join(path.split("/")[:3]) or path
        by_prefix[prefix] = by_prefix.get(prefix, 0) + 1

    print(
        f"matched: {len(matched_ops)}   v1-not-yet-ported: {len(unported)}   "
        f"uuid gaps: {len(live_gaps)}   drift: {len(drift)}"
    )
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
