#!/usr/bin/env python
"""Export the live v2 OpenAPI schema to `frontend/schema.v2.yml`.

The generated TypeScript client is built from a committed schema file. Until
this existed that file was `frontend/schema.yml` — **v1's frozen 306-operation
baseline**, which is also the left-hand side of `scripts/schema_parity_diff.py`
and must never be overwritten. The consequence was that the typed client
tracked v1 rather than the backend it talks to, and CI's "generated client is
current" step only ever checked the client against that stale input.

So this writes a *separate* file. `frontend/schema.yml` stays exactly as it is,
the parity diff keeps its v1 reference, and `openapi-ts.config.ts` reads
`schema.v2.yml`.

Output is deterministic — sorted keys, fixed width — so CI can run this and
`git diff --exit-code` to catch a backend change that nobody regenerated the
client for. Same shape as the delta-goldens freshness check.

Usage:
    uv run python scripts/export_openapi.py [--check]

    --check  exit 1 if the committed file is stale, without rewriting it
"""

import argparse
import json
import sys
from pathlib import Path

import django
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
TARGET = REPO_ROOT / "frontend" / "schema.v2.yml"

sys.path.insert(0, str(REPO_ROOT))

from scripts.django_settings import pin_settings  # noqa: E402  (needs REPO_ROOT on sys.path)

pin_settings()


def render() -> str:
    """The live schema as deterministic YAML."""
    django.setup()
    # Imported after setup(): config.api builds the NinjaAPI, which imports
    # every domain router and therefore every model.
    from config.api import api

    # path_prefix matches scripts/schema_parity_diff.py, so both sides of the
    # parity comparison describe the same URLs.
    spec = api.get_openapi_schema(path_prefix="/api")
    # Round-trip through JSON before dumping: ninja returns dict SUBCLASSES in
    # places (the cookie security scheme is one), which yaml.safe_dump refuses
    # to represent. This normalises every node to a plain type and, since the
    # schema must be JSON-serialisable anyway, cannot lose information.
    plain = json.loads(json.dumps(spec))
    return yaml.safe_dump(plain, sort_keys=True, default_flow_style=False, width=100)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail if the committed schema is stale instead of rewriting it",
    )
    args = parser.parse_args()

    rendered = render()
    if args.check:
        if not TARGET.exists():
            print(f"{TARGET.relative_to(REPO_ROOT)} does not exist — run this script.")
            return 1
        if TARGET.read_text() != rendered:
            print(
                f"{TARGET.relative_to(REPO_ROOT)} is stale: the backend's schema has "
                "changed since it was exported. Run:\n"
                "  uv run python scripts/export_openapi.py\n"
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
