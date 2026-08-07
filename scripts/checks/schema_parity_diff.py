"""Compare v2's live OpenAPI surface against v1's frozen contract (schema.yml).

The plan's standing API-parity instrument. Three categories:

- DRIFT (fails, exit 1): an operation exists at the same path+method in both
  schemas but with a different operationId, or v2 exposes an operation v1
  never had that is not covered by the parity ledger
  (docs/accepted-api-differences.yml, matched on the ledger's `operation`).
- NOT YET PORTED (informational): v1 operations absent from v2 — expected
  while the rewrite is in flight; printed as a count with per-prefix detail.
- MATCHED: path+method+operationId agree.
- CONTRACT GAPS: a property of an operation present in both schemas that v2
  declares more weakly than v1 — a lost `format: uuid`, a value that v1
  guarantees and v2 admits null for, or a property v1 requires and v2 makes
  optional. All three have one cause: DRF derived v1's contract from the
  models, while v2 hand-writes its ninja schemas, so nothing ties the wire
  back to model truth. The known set lives in
  scripts/schema-contract-gaps.txt and the live set must EQUAL it: a new gap
  fails (that is the accumulation this exists to stop), and a gap fixed
  without updating the file fails too, so the file cannot rot into a
  wishlist. It ratchets DOWN to zero.

A ratcheting baseline (scripts/schema-parity-baseline.txt) records every
operationId that has ever matched: once ported, an operation disappearing
from v2 is DRIFT, not "not yet ported" — deleting an endpoint requires a
deliberate baseline regeneration. Run with --update-baseline after adding
operations; CI verifies the committed baseline is current.

Usage: uv run python -m scripts.checks.schema_parity_diff [--update-baseline]
Exit 0 = no unexplained drift and baseline current.
"""

import re
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, NamedTuple

import yaml

from scripts import REPO_ROOT
from scripts.django_settings import pin_settings

REPO = REPO_ROOT

pin_settings()

V1_SCHEMA = REPO / "frontend" / "schema.yml"
LEDGER = REPO / "docs" / "accepted-api-differences.yml"
BASELINE = REPO / "scripts" / "schema-parity-baseline.txt"
GAPS = REPO / "scripts" / "schema-contract-gaps.txt"

METHODS = ("get", "post", "put", "patch", "delete")

Operations = dict[tuple[str, str], str]  # (path, method) -> operationId


class Operation(NamedTuple):
    """An operation object plus the route template it was declared under.

    The route is carried because path parameters are matched to their URL slot
    by placeholder name, and the key of OperationSpecs has those names blanked
    to `{}` so the two schemas' differing names compare equal.
    """

    route: str
    spec: dict[str, Any]


OperationSpecs = dict[tuple[str, str], Operation]  # (wire path, method) -> operation


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
            specs[(_wire_path(path), method)] = Operation(path, merged)
    return specs


def _deref(spec: dict[str, Any], node: Any, seen: tuple[str, ...] = ()) -> dict[str, Any]:
    """Follow $ref chains. Returns {} on a cycle rather than recursing forever.

    The cycle return is deliberate (these schemas are recursive: a Job carries
    events that carry a job). An UNRESOLVABLE pointer is not — it would make
    _walk_properties report zero properties and silently under-report every
    gap below it, so it raises.
    """
    while isinstance(node, dict) and "$ref" in node:
        ref = str(node["$ref"])
        if ref in seen:
            return {}
        seen += (ref,)
        if not ref.startswith("#/"):
            # Both generators emit in-document components; a remote pointer
            # would resolve to {} and hide whatever it pointed at.
            raise ValueError(f"Unsupported non-local $ref {ref!r}")
        cursor: Any = spec
        for part in ref.removeprefix("#/").split("/"):
            if not isinstance(cursor, dict) or part not in cursor:
                raise KeyError(f"Unresolvable $ref {ref!r} (missing segment {part!r})")
            cursor = cursor[part]
        node = cursor
    return node if isinstance(node, dict) else {}


class PropertyInfo(NamedTuple):
    """A property's declaration, plus whether its parent marks it required.

    Required-ness lives beside the schema rather than in a parallel map
    because both halves are read together for every comparison, and a second
    walk to recover it would be a sibling of this one.
    """

    schema: dict[str, Any]
    required: bool


Properties = dict[tuple[str, ...], PropertyInfo]


def _walk_properties(
    spec: dict[str, Any],
    node: Any,
    prefix: tuple[str, ...] = (),
    seen_nodes: frozenset[int] = frozenset(),
    out: Properties | None = None,
) -> Properties:
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

    required = {str(name) for name in resolved.get("required") or []}
    for name, raw in (resolved.get("properties") or {}).items():
        child = _deref(spec, raw)
        out.setdefault((*prefix, str(name)), PropertyInfo(child, str(name) in required))
        _walk_properties(spec, child, (*prefix, str(name)), seen_nodes, out)
    if "items" in resolved:
        _walk_properties(spec, resolved["items"], (*prefix, "[]"), seen_nodes, out)
    # Combinator branches share the parent's prefix, so a property declared by
    # two branches of a `oneOf` collapses to one entry and setdefault keeps an
    # arbitrary branch. Sound today and verified: v2 has no oneOf/anyOf
    # response unions, and v1's one case (POST /api/job/cost_lines/{}/approve/,
    # where both branches declare `success` and `message`) yields no gap either
    # way. It stops being sound the moment v2 grows a response union — give
    # branches distinct prefixes then.
    for combinator in ("allOf", "oneOf", "anyOf"):
        for branch in resolved.get(combinator) or []:
            _walk_properties(spec, branch, prefix, seen_nodes, out)
    return out


def _body_properties(spec: dict[str, Any], operation: dict[str, Any]) -> Properties:
    """Request and response properties, namespaced so a body cannot mask a response."""
    found: Properties = {}
    body = _deref(spec, operation.get("requestBody") or {})
    for media in (body.get("content") or {}).values():
        for path, info in _walk_properties(spec, (media or {}).get("schema") or {}).items():
            found.setdefault(("request", *path), info)
    for code, response in (operation.get("responses") or {}).items():
        resolved = _deref(spec, response)
        for media in (resolved.get("content") or {}).values():
            for path, info in _walk_properties(spec, (media or {}).get("schema") or {}).items():
                found.setdefault((f"response:{code}", *path), info)
    return found


def _parameters(spec: dict[str, Any], operation: Operation) -> Properties:
    """Parameter schemas, keyed so both schemas agree on what matches what.

    Query parameter names ARE contract, so they key by name. PATH parameter
    names are template labels — v1's `{id}` is v2's `{job_id}` for the same
    URL — so they key by their SLOT in the route, because a name match would
    silently skip the 15 of v1's 102 uuid path parameters that v2 renamed.

    The slot comes from the position of the matching placeholder in the route,
    never from the parameter's index in the `parameters` array. OpenAPI binds a
    path parameter to its placeholder by name and says nothing about array
    order, and v1 exercises that freedom: 11 of its operations list them out of
    URL order, including `/api/job/jobs/{job_id}/files/{file_id}/` where the
    array runs file_id, job_id. Keying by array index compared v1's file_id
    against v2's job_id on every one of them.
    """
    slots = {name: index for index, name in enumerate(re.findall(r"\{([^}]+)\}", operation.route))}
    found: Properties = {}
    for raw in operation.spec.get("parameters") or []:
        parameter = _deref(spec, raw)
        schema = _deref(spec, parameter.get("schema") or {})
        info = PropertyInfo(schema, bool(parameter.get("required", False)))
        location = parameter.get("in")
        name = str(parameter.get("name"))
        if location == "path":
            if name not in slots:
                raise ValueError(
                    f"path parameter {name!r} on {operation.route!r} matches no placeholder"
                )
            found.setdefault(("path-param", str(slots[name])), info)
        elif location == "query":
            found.setdefault(("query-param", name), info)
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


def _is_nullable(spec: dict[str, Any], node: dict[str, Any], depth: int = 0) -> bool:
    """Whether this property admits null, in either schema dialect.

    Same dual-spelling trap as _is_uuid, in the other direction: v1 is 3.0
    (`nullable: true`), v2 is 3.1 (`anyOf: [{...}, {type: null}]`, or a type
    list containing "null"). Reading only one dialect would call every v2
    optional field a regression.

    allOf is deliberately NOT recursed. `allOf` means "satisfies every
    branch", so a null branch inside it cannot make the whole nullable;
    treating it as if it did would invent gaps that are not there.
    """
    if depth > 8:  # union nesting is shallow; this only bounds pathological input
        return False
    resolved = _deref(spec, node)
    if resolved.get("nullable") is True:
        return True
    declared = resolved.get("type")
    if declared == "null" or (isinstance(declared, list) and "null" in declared):
        return True
    for combinator in ("anyOf", "oneOf"):
        for branch in resolved.get(combinator) or []:
            if _is_nullable(spec, branch, depth + 1):
                return True
    return False


class Side(NamedTuple):
    """One schema's declaration of a property, with the spec it must be read against.

    The two travel together because resolving a `$ref` needs the document it
    came from, and a predicate handed a declaration without its spec cannot
    follow one.
    """

    spec: dict[str, Any]
    info: PropertyInfo


def _weaker_uuid(v1: Side, v2: Side) -> bool:
    """v1 pins the value to a uuid and v2 accepts any string."""
    return _is_uuid(v1.spec, v1.info.schema) and not _is_uuid(v2.spec, v2.info.schema)


def _weaker_nullable(v1: Side, v2: Side) -> bool:
    """v1 guarantees a value and v2 admits null."""
    return not _is_nullable(v1.spec, v1.info.schema) and _is_nullable(v2.spec, v2.info.schema)


def _weaker_required(v1: Side, v2: Side) -> bool:
    """v1 guarantees the property is present and v2 lets it be absent."""
    return v1.info.required and not v2.info.required


class Weakening(NamedTuple):
    kind: str
    is_weaker: Callable[[Side, Side], bool]
    bodies_only: bool


# One concept — "v2's declaration is weaker than v1's" — so one walker, one
# record file and one ratchet. Three predicates with three near-identical
# gap functions and three baseline files would be the sibling pathology the
# rewrite exists to remove (ADR 0039).
#
# `nullable` is bodies-only, because a URL cannot carry null. A query string
# transmits text or nothing at all, so "absent" is the only way a parameter
# says no-value and `anyOf: [{...}, {type: null}]` is merely how ninja spells
# a `| None = None` default. Null is a distinguishable wire value only inside
# a JSON body or response.
#
# It suppresses 34 parameter differences, and NOT because `required` covers
# them: measured, `required` reports 1 of the 34 and the other 33 are optional
# in both schemas and reported by nothing. They are suppressed because they
# are not defects.
#
# The blind spot this leaves, currently zero instances: a parameter v1
# declares required-and-non-nullable that v2 declares required-but-nullable is
# caught by neither check.
WEAKENINGS = (
    Weakening("uuid", _weaker_uuid, bodies_only=False),
    Weakening("nullable", _weaker_nullable, bodies_only=True),
    Weakening("required", _weaker_required, bodies_only=False),
)


def _contract_gaps(v1_spec: dict[str, Any], v2_spec: dict[str, Any]) -> set[str]:
    """Every property where v2's declaration is weaker than v1's.

    A property v1 has and v2 does not expose at all is NOT a gap: that is an
    operation-shape difference, which the ledger already governs.
    """
    v1_ops, v2_ops = _operation_specs(v1_spec), _operation_specs(v2_spec)
    gaps: set[str] = set()
    for key in sorted(set(v1_ops) & set(v2_ops)):
        path, method = key
        v1_op, v2_op = v1_ops[key], v2_ops[key]
        v1_props = {**_body_properties(v1_spec, v1_op.spec), **_parameters(v1_spec, v1_op)}
        v2_props = {**_body_properties(v2_spec, v2_op.spec), **_parameters(v2_spec, v2_op)}
        for prop_path, v1_info in v1_props.items():
            v2_info = v2_props.get(prop_path)
            if v2_info is None:
                continue
            is_parameter = prop_path[0].endswith("-param")
            v1_side, v2_side = Side(v1_spec, v1_info), Side(v2_spec, v2_info)
            for weakening in WEAKENINGS:
                if weakening.bodies_only and is_parameter:
                    continue
                if weakening.is_weaker(v1_side, v2_side):
                    gaps.add(f"{weakening.kind} {method.upper()} {path} :: {'.'.join(prop_path)}")
    return gaps


def _read_record_file(path: Path) -> set[str]:
    """The non-comment entries of a committed ratchet file.

    Absence is an error, not an empty baseline: returning an empty set would
    relabel every known entry as a brand-new regression and bury the real
    problem (the missing file) under that noise. Bootstrapping a new ratchet
    means committing the file with only its header — a deliberate act, which
    is what makes "this list may only shrink" mean anything.
    """
    if not path.exists():
        # --update-baseline cannot rescue this: main() reads the file to build
        # the argument it passes, so the read happens before `update` is ever
        # examined. Naming that flag here would send the reader down a path
        # that fails the same way (ADR 0038: say the remedy that works).
        raise FileNotFoundError(
            f"{path} is missing. Create it containing only its header comment, then run "
            "--update-baseline to fill it. Bootstrapping is deliberate: an empty ratchet "
            "silently forgives every entry the file used to hold."
        )
    # Strip BEFORE testing for the comment marker: an indented comment would
    # otherwise be read as an entry and reported as a stale recorded gap.
    return {
        stripped
        for stripped in (line.strip() for line in path.read_text().splitlines())
        if stripped and not stripped.startswith("#")
    }


GAPS_HEADER = """\
# Properties where v2's declared contract is WEAKER than v1's, one per line,
# tagged by how it is weaker:
#
#   uuid      v1 pins `format: uuid`; v2 accepts any string.
#   nullable  v1 guarantees a value; v2 admits null.
#   required  v1 guarantees the property is present; v2 lets it be absent.
#
# All three come from the same cause: DRF derived v1's contract from the
# models, while v2 hand-writes its ninja schemas, so nothing ties the wire
# back to model truth. See docs/adr/ for the derivation decision.
#
# This list may only SHRINK. A gap missing from it fails (a new regression —
# the accumulation this exists to stop); a listed gap that no longer exists
# also fails, so the file cannot rot into a wishlist. Regenerate with
# --update-baseline when you fix one.
"""


def _apply_gap_ratchet(live: set[str], recorded: set[str], update: bool) -> list[str]:
    """The live gap set must EQUAL the recorded one, in both directions."""
    if update:
        GAPS.write_text(GAPS_HEADER + "\n".join(sorted(live)) + "\n")
        print(f"contract gaps recorded: {len(live)}")
        return []

    drift = [
        f"NEW contract regression (v2 declares this more weakly than v1): {gap}"
        for gap in sorted(live - recorded)
    ]
    drift += [
        f"contract gap recorded but no longer present — regenerate the file: {gap}"
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
    return _read_record_file(BASELINE)


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

    # Both record files are read up front, before either is written. Reading
    # them lazily let a missing gaps file raise AFTER --update-baseline had
    # already rewritten the operation baseline, leaving the two ratchets
    # inconsistent on the failure path.
    baseline, recorded_gaps = _baseline(), _read_record_file(GAPS)

    drift, matched_ops = _classify(v1, v2, _ledgered_operations())
    drift += _apply_baseline_ratchet(matched_ops, baseline, update_baseline)

    live_gaps = _contract_gaps(v1_spec, v2_spec)
    drift += _apply_gap_ratchet(live_gaps, recorded_gaps, update_baseline)

    unported = sorted(set(v1) - set(v2))
    by_prefix: dict[str, int] = {}
    for path, _method in unported:
        prefix = "/".join(path.split("/")[:3]) or path
        by_prefix[prefix] = by_prefix.get(prefix, 0) + 1

    print(
        f"matched: {len(matched_ops)}   v1-not-yet-ported: {len(unported)}   "
        f"contract gaps: {len(live_gaps)}   drift: {len(drift)}"
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
