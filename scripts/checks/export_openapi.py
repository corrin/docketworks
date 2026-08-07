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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail if the committed schema is stale instead of rewriting it",
    )
    args = parser.parse_args()

    spec = build_spec()
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
