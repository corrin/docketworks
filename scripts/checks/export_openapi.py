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


pin_settings()


def render() -> str:
    """The live schema as deterministic YAML."""
    django.setup()
    # Imported after setup(): config.api builds the NinjaAPI, which imports
    # every domain router and therefore every model.
    from config.api import api

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
