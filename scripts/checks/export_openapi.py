#!/usr/bin/env python
"""Export the live v2 OpenAPI schema to frontend/schema.v2.yml.

The frontend generates its typed client from this file, so it is the one
place the wire contract is written down. `--check` fails when the committed
copy is stale, because a client generated from a stale schema describes an
API that no longer exists — and tsc would still compile it happily.
"""

import argparse
import json

import django
import yaml

from scripts import REPO_ROOT
from scripts.django_settings import pin_settings

TARGET = REPO_ROOT / "frontend" / "schema.v2.yml"

SCHEMA_REF_PREFIX = "#/components/schemas/"

#: v1 apps that v2 does not have. A route naming one is a URL that survived the
#: app it was named after — v1 served pay items from `/api/workflow/…` and there
#: is no workflow app here. Pinned at zero rather than counted: CLAUDE.md keeps
#: exact-URL parity ONLY where an external party holds the URL (the Xero OAuth
#: redirect, the Xero webhook, CRM phone ingestion, ServiceApiKey consumers),
#: and none of those name a dissolved app, so there is no legitimate instance.
#:
#: Deliberately NOT "every segment names a v2 app": `companies`, `timesheets`
#: and `people` are all correct and all fail that rule, which would make the
#: check noise. This one has no false positives.
DISSOLVED_V1_APPS = frozenset({"workflow", "client"})


pin_settings()


def build_spec() -> dict[str, object]:
    """The live OpenAPI schema, as plain JSON types.

    ``path_prefix="/api"`` so the paths here are the URLs a client actually
    calls, not the router-relative ones.
    """
    django.setup()
    # Imported after setup(): config.api builds the NinjaAPI, which imports
    # every domain router and therefore every model.
    from config.api import api

    spec = api.get_openapi_schema(path_prefix="/api")
    # Round-trip through JSON: ninja returns dict SUBCLASSES in places (the
    # cookie security scheme is one), which yaml.safe_dump refuses to
    # represent. Since the schema must be JSON-serialisable anyway, this
    # normalises every node without losing information.
    # json.loads is Any-typed; the cast records what the round-trip actually
    # produces rather than letting Any leak into every caller (ADR 0028).
    plain: dict[str, object] = json.loads(json.dumps(spec))
    return plain


def render(spec: dict[str, object]) -> str:
    """The schema as deterministic YAML."""
    return yaml.safe_dump(spec, sort_keys=True, default_flow_style=False, width=100)


def _routes_naming_a_dissolved_app(spec: dict[str, object]) -> list[str]:
    """Paths carrying the name of a v1 app that v2 dissolved."""
    paths = spec.get("paths")
    if not isinstance(paths, dict):
        raise TypeError(f"exported schema has no paths mapping (got {type(paths).__name__})")
    return sorted(
        path
        for path in paths
        if DISSOLVED_V1_APPS & {segment.lower() for segment in path.split("/")}
    )


def _referenced_schemas(node: object, found: set[str]) -> None:
    """Collect every component schema name reachable from a spec fragment."""
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith(SCHEMA_REF_PREFIX):
            found.add(ref[len(SCHEMA_REF_PREFIX) :])
        for value in node.values():
            _referenced_schemas(value, found)
    elif isinstance(node, list):
        for value in node:
            _referenced_schemas(value, found)


def response_schema_names(spec: dict[str, object]) -> set[str]:
    """Every schema a response body can contain, following nested refs."""
    schemas = _components_schemas(spec)
    seeds: set[str] = set()
    paths = spec.get("paths")
    if not isinstance(paths, dict):
        raise TypeError(f"exported schema has no paths mapping (got {type(paths).__name__})")
    for operations in paths.values():
        for operation in operations.values():
            if isinstance(operation, dict):
                _referenced_schemas(operation.get("responses", {}), seeds)

    reachable: set[str] = set()
    pending = list(seeds)
    while pending:
        name = pending.pop()
        if name in reachable or name not in schemas:
            continue
        reachable.add(name)
        nested: set[str] = set()
        _referenced_schemas(schemas[name], nested)
        pending.extend(nested)
    return reachable


def _components_schemas(spec: dict[str, object]) -> dict[str, dict[str, object]]:
    components = spec.get("components")
    if not isinstance(components, dict):
        raise TypeError(f"exported schema has no components (got {type(components).__name__})")
    schemas = components.get("schemas")
    if not isinstance(schemas, dict):
        raise TypeError(f"components carries no schemas mapping (got {type(schemas).__name__})")
    return schemas


def optional_response_properties(spec: dict[str, object]) -> dict[str, list[str]]:
    """Response properties a client is told may be absent, by schema name.

    Pinned at zero. ninja serialises with ``exclude_unset``, ``exclude_defaults``
    and ``exclude_none`` all false, so every declared field is in every body —
    an optional response property is a claim the server cannot make true, and it
    costs each consumer a branch for a case that never happens.

    Inherit ``apps.core.schemas.ResponseSchema`` to fix one. It is deliberately
    not a nullability check: ``| None`` on a response is often correct, and
    deciding needs the producing service read, so that stays per-slice.
    """
    schemas = _components_schemas(spec)
    offenders: dict[str, list[str]] = {}
    for name in sorted(response_schema_names(spec)):
        schema = schemas[name]
        properties = schema.get("properties")
        if not isinstance(properties, dict):
            continue
        required = schema.get("required")
        declared = set(required) if isinstance(required, list) else set()
        missing = sorted(field for field in properties if field not in declared)
        if missing:
            offenders[name] = missing
    return offenders


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail if the committed schema is stale instead of rewriting it",
    )
    args = parser.parse_args()

    spec = build_spec()
    loose = optional_response_properties(spec)
    if loose:
        print(
            "These response properties are published as optional, but ninja "
            "sends every declared field in every body:\n"
            + "\n".join(f"  {name}: {', '.join(fields)}" for name, fields in loose.items())
            + "\n\nInherit apps.core.schemas.ResponseSchema on the schema. A client "
            "told a field may be absent has to branch for a case the server "
            "cannot produce.",
        )
        return 1

    offenders = _routes_naming_a_dissolved_app(spec)
    if offenders:
        print(
            "These routes are named after a v1 app that v2 does not have "
            f"({', '.join(sorted(DISSOLVED_V1_APPS))}):\n"
            + "\n".join(f"  {path}" for path in offenders)
            + "\n\nRename to the app the code actually lives in. Nothing external holds "
            "these URLs, so there is nothing to preserve.",
        )
        return 1

    rendered = render(spec)
    if args.check:
        if not TARGET.exists():
            print(f"{TARGET.relative_to(REPO_ROOT)} does not exist — run this script.")
            return 1
        if TARGET.read_text() != rendered:
            print(
                f"{TARGET.relative_to(REPO_ROOT)} is stale: the backend's schema has "
                "changed since it was exported. Run:\n"
                "  uv run python -m scripts.checks.export_openapi\n"
                "  cd frontend && npm run generate-client\n"
                "and commit both."
            )
            return 1
        print(f"{TARGET.relative_to(REPO_ROOT)} is current")
        return 0

    TARGET.write_text(rendered)
    print(f"wrote {TARGET.relative_to(REPO_ROOT)} ({len(rendered):,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
