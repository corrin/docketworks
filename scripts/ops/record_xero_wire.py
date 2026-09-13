#!/usr/bin/env python
"""Record, from the real tenant, the wire body of every route the fake Xero serves.

One pass, about thirty calls, writes ``apps/xero/fake/recordings/<name>.json``
with the body exactly as Xero sent it (personal values scrubbed, long lists
cut to two elements) and the run that produced it. The same catalogue is what
``apps/xero/tests/test_fake_recordings_current.py`` re-fetches to alarm on
drift, so recording and checking cannot describe different routes.

Refuses a production target: the pass only reads, but a shape captured from
a live organisation carries its values, and the dev tenant exists for this.

Usage:
    uv run python -m scripts.ops.record_xero_wire                  # every route
    uv run python -m scripts.ops.record_xero_wire tax_rates quote  # these only
"""

import json
import sys
from datetime import UTC, datetime
from decimal import Decimal
from importlib.metadata import version
from pathlib import Path

from scripts.bootstrap import setup_django

setup_django()

from apps.xero.auth import (  # noqa: E402 -- Django must be configured first
    get_api_client,
    get_tenant_id,
)
from apps.xero.fake.recordings.catalogue import (  # noqa: E402
    LIST_ELEMENTS_KEPT,
    SCRUBBED_KEYS,
    capture_all,
)
from apps.xero.operator_guards import assert_not_production_target  # noqa: E402
from apps.xero.quota import read_day_quota  # noqa: E402

RECORDINGS_DIR = Path(__file__).resolve().parents[2] / "apps" / "xero" / "fake" / "recordings"


def _json_default(value: object) -> float:
    if isinstance(value, Decimal):
        return float(value)
    raise TypeError(f"{type(value).__name__} is not JSON serialisable")


def main() -> int:
    """Capture every route (or the named ones) and write one file per recording."""
    only = frozenset(sys.argv[1:]) or None
    assert_not_production_target()
    reading = read_day_quota()
    recorded_at = datetime.now(tz=UTC).isoformat(timespec="seconds")
    print(f"Recording from {reading.organisation_name} ({reading.day_remaining} calls left today)")
    count = 0
    for capture in capture_all(get_api_client(), get_tenant_id(), only):
        document = {
            "recorded_at": recorded_at,
            "organisation": reading.organisation_name,
            "sdk": f"xero-python {version('xero-python')}",
            "scrubbed_keys": sorted(SCRUBBED_KEYS),
            "lists_kept_to": LIST_ELEMENTS_KEPT if capture.truncated else None,
            "request": {"method": capture.method, "path": capture.path, "query": capture.query},
            "response": {
                "status": capture.status,
                "content_type": capture.content_type,
                "content_disposition": capture.content_disposition,
            },
            "body": capture.body,
        }
        target = RECORDINGS_DIR / f"{capture.name}.json"
        target.write_text(json.dumps(document, indent=2, default=_json_default) + "\n")
        print(f"  {capture.name:24s} {capture.status} {capture.method} {capture.path}")
        count += 1
    print(f"Wrote {count} recordings to {RECORDINGS_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
