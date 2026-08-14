#!/usr/bin/env python
"""Diagnostic: inspect phone provider CDR rows and download recording samples.

This is not a Celery Beat test harness. Provider deletion must be tested
through the production Celery Beat task path
(apps/crm/tasks.py cleanup task -> delete_archived_provider_recordings),
not through this script.

Reuses apps/crm/services/phone_call_service.py's PhoneProviderPortalClient —
the same portal client the Beat sync uses — rather than carrying a second
login/CDR/download implementation (ADR 0039). Credentials therefore come
from the PhoneProviderSettings solo row, not environment variables.
"""

import argparse
import json
import logging
import os
import sys
from datetime import date, timedelta
from pathlib import Path

# scripts/ops/ is two levels below the repo root; see
# scripts/ops/setup_dev_logins.py for why this is inserted explicitly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from django.utils.timezone import localdate  # noqa: E402 -- Django must be configured first

from apps.crm.models import PhoneCallRecord  # noqa: E402
from apps.crm.services.phone_call_service import (  # noqa: E402
    PhoneProviderPortalClient,
    ProviderPayload,
    _config,
)

LOG = logging.getLogger("phone-provider-diagnostic")


def parse_args() -> argparse.Namespace:
    """Parse the probe's command-line options."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-date", type=date.fromisoformat)
    parser.add_argument("--end-date", type=date.fromisoformat, default=localdate())
    parser.add_argument("--months", type=int)
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--output-dir", default="/tmp/phone-recording-probe")  # noqa: S108 -- throwaway diagnostic samples, not a privileged path
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--page-delay", type=float, default=0.3)
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
    )
    start_date = args.start_date
    if start_date is None and args.months:
        start_date = args.end_date - timedelta(days=args.months * 31)
    if start_date is None:
        start_date = args.end_date - timedelta(days=31)

    client = PhoneProviderPortalClient(_config())
    client.login()

    calls: list[ProviderPayload] = []
    for page in client.iter_call_pages(
        page_delay=args.page_delay,
        start_date=start_date,
        end_date=args.end_date,
    ):
        calls.extend(page.calls)

    recordings = [row for row in calls if row.get("RecordingId")]
    print(f"Fetched {len(calls)} call rows")
    print(f"Found {len(recordings)} rows with RecordingId")

    if args.dry_run:
        for row in recordings:
            print(json.dumps(row, sort_keys=True))
        return 0

    limit = len(recordings) if args.limit == 0 else args.limit
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    downloaded = 0
    for row in recordings[:limit]:
        # download_recording reads only raw_json, so an unsaved row is enough
        # to reuse the real client instead of duplicating its download logic.
        content, filename, _content_type = client.download_recording(PhoneCallRecord(raw_json=row))
        # The name comes from the response's content-disposition, so the
        # skip-existing check can only happen after the download — the cost is
        # a re-fetch of already-sampled recordings, acceptable at probe sizes.
        path = output_dir / filename
        if path.exists() and path.stat().st_size:
            print(f"skip existing {path}")
            continue
        path.write_bytes(content)
        downloaded += 1
        print(f"downloaded {row['RecordingId']} {len(content)} bytes -> {path}")

    print(f"Downloaded {downloaded}/{min(limit, len(recordings))} recordings")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
