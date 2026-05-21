#!/usr/bin/env python
"""POC: Download call logs and recordings from 2talk ISP portal.

Usage:
  # Dry-run: list calls with recordings (no downloading)
  python scripts/poc_2talk_scraper.py --dry-run --months 3

  # Download all recordings from the last 3 months
  python scripts/poc_2talk_scraper.py --months 3

  # Target a specific bill period
  python scripts/poc_2talk_scraper.py --bill-period 2026-05-04 --dry-run

  # Download recordings to a specific directory
  python scripts/poc_2talk_scraper.py --output-dir ./call_recordings --months 6

Credentials are read from environment variables:
  ISP_URL, ISP_USERNAME, ISP_PASSWORD
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from time import sleep
from typing import Optional

import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

LOG = logging.getLogger("2talk-poc")

BASE_URL = os.getenv("ISP_URL", "https://now.2talk.co.nz/").rstrip("/")
USERNAME = os.getenv("ISP_USERNAME")
PASSWORD = os.getenv("ISP_PASSWORD")

if not USERNAME or not PASSWORD:
    print(
        "Error: ISP_USERNAME and ISP_PASSWORD must be set in environment",
        file=sys.stderr,
    )
    sys.exit(1)

CDR_ENDPOINT = "/json/account/getCdr"
RECORDING_ENDPOINT = "/account/dlrecording"

# ---------------------------------------------------------------------------
# Session / auth
# ---------------------------------------------------------------------------


def login(session: requests.Session) -> bool:
    """Authenticate with the 2talk portal. Returns True on success."""
    resp = session.post(
        f"{BASE_URL}/",
        data={"username": USERNAME, "password": PASSWORD},
        headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
        },
    )
    if resp.status_code == 200 and "/account/status" in resp.url:
        LOG.info("Login successful (redirected to %s)", resp.url)
        return True
    LOG.error("Login failed (url=%s, status=%s)", resp.url, resp.status_code)
    return False


def make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/javascript, */*; q=0.01",
        }
    )
    return session


# ---------------------------------------------------------------------------
# CDR data fetching
# ---------------------------------------------------------------------------


def fetch_cdr_page(
    session: requests.Session,
    bill_period: str,
    page: int,
    account_code: str,
) -> list[dict]:
    """Fetch one page of CDR records. Returns list of call dicts."""
    resp = session.post(
        f"{BASE_URL}{CDR_ENDPOINT}",
        data={
            "BillPeriod": bill_period,
            "p": str(page),
            "accountcode": account_code,
        },
    )
    if resp.status_code != 200:
        LOG.warning(
            "CDR returned %s for period=%s page=%s", resp.status_code, bill_period, page
        )
        return []
    try:
        data = resp.json()
    except json.JSONDecodeError:
        LOG.warning("CDR response not JSON for period=%s page=%s", bill_period, page)
        return []
    if not isinstance(data, list):
        return []
    return data


def iter_calls(
    session: requests.Session,
    bill_periods: list[str],
    account_code: str,
    page_delay: float = 0.3,
) -> "iter":
    """Yield every call record across the given bill periods."""
    for bp in bill_periods:
        LOG.info("Fetching calls for bill period %s ...", bp)
        page = 1
        consecutive_empty = 0
        while True:
            calls = fetch_cdr_page(session, bp, page, account_code)
            if not calls:
                consecutive_empty += 1
                if consecutive_empty >= 2:
                    break
                page += 1
                continue
            consecutive_empty = 0
            for call in calls:
                yield call
            page += 1
            if page_delay:
                sleep(page_delay)


def calls_with_recordings(calls: "iter") -> list[dict]:
    """Return only calls that have a recording."""
    return [c for c in calls if c.get("RecordingId")]


# ---------------------------------------------------------------------------
# Recording download
# ---------------------------------------------------------------------------


def download_recording(
    session: requests.Session,
    call: dict,
    output_dir: Path,
    account_code: str,
) -> Optional[Path]:
    """Download a single recording. Returns the file path or None."""
    rid = call["RecordingId"]
    origin = call.get("origin", "unknown")
    destination = call.get("destination", "unknown")
    date_str = f"{call['calldate']} - {call['calltime']}"

    resp = session.get(
        f"{BASE_URL}{RECORDING_ENDPOINT}",
        params={
            "AccountCode": account_code,
            "rid": rid,
            "aparty": origin,
            "bparty": destination,
            "date": date_str,
        },
    )

    if resp.status_code != 200:
        LOG.warning("Download failed for rid=%s: status=%s", rid, resp.status_code)
        return None

    content_type = resp.headers.get("content-type", "")
    if "audio" not in content_type and "mpeg" not in content_type:
        LOG.warning("Unexpected content-type '%s' for rid=%s", content_type, rid)
        return None

    # Derive filename from Content-Disposition or build one
    disposition = resp.headers.get("content-disposition", "")
    filename = None
    if "filename=" in disposition:
        # Extract filename from header like: attachment; filename="foo.mp3"
        import re

        m = re.search(r'filename[^;=]*=["\']?([^"\';\r\n]+)', disposition)
        if m:
            filename = m.group(1)

    if not filename:
        filename = f"{date_str.replace(' ', '_').replace(':', '-')}_{origin}_to_{destination}.mp3"

    output_dir.mkdir(parents=True, exist_ok=True)
    filepath = output_dir / filename

    content = resp.content

    # Strip spurious "200\r" or "200" prefix that the server prepends
    if content[:3] == b"200":
        content = content[3:].lstrip(b"\r\n ")

    if not content:
        LOG.warning("Empty content after cleanup for rid=%s", rid)
        return None

    filepath.write_bytes(content)
    LOG.info("Downloaded: %s (%s bytes)", filepath.name, len(content))
    return filepath


# ---------------------------------------------------------------------------
# Bill period helpers
# ---------------------------------------------------------------------------


def generate_bill_periods(months_back: int) -> list[str]:
    """Generate bill period strings like '2026-06-04' for the last N months.

    Bill periods are always the 4th of the month. The period for calls made
    in a given month is the 4th of the *following* month (e.g. May calls
    appear in the 2026-06-04 bill period).
    """
    from datetime import datetime

    from dateutil.relativedelta import relativedelta

    today = datetime.today()
    periods = []

    # Start from next month's bill period (covers current partial month)
    # and go back N months
    for i in range(months_back + 1):
        d = today + relativedelta(months=1 - i)
        bp = f"{d.year}-{d.month:02d}-04"
        periods.append(bp)

    return sorted(set(periods))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="POC: Download 2talk call logs and recordings",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List calls with recordings but do not download",
    )
    parser.add_argument(
        "--months",
        type=int,
        default=3,
        help="Number of months of bill periods to fetch (default: 3)",
    )
    parser.add_argument(
        "--bill-period",
        type=str,
        default=None,
        help="Fetch a single specific bill period (e.g. 2026-06-04)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="./recordings",
        help="Directory to save recordings (default: ./recordings)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Verbose logging",
    )
    parser.add_argument(
        "--account-code",
        type=str,
        default=None,
        help="2talk account code (default: read from ISP_USERNAME env var)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    account_code = args.account_code or USERNAME

    if args.bill_period:
        bill_periods = [args.bill_period]
    else:
        bill_periods = generate_bill_periods(args.months)

    LOG.info("Bill periods to fetch: %s", bill_periods)
    LOG.info("Account code: %s", account_code)

    session = make_session()
    if not login(session):
        sys.exit(1)

    # Collect all calls
    all_calls = []
    recordings = []
    for call in iter_calls(session, bill_periods, account_code):
        all_calls.append(call)
        if call.get("RecordingId"):
            recordings.append(call)

    LOG.info(
        "Fetched %d calls total, %d with recordings", len(all_calls), len(recordings)
    )

    if args.dry_run:
        print(f"\n=== {len(recordings)} call(s) with recordings ===\n")
        for call in recordings:
            print(
                f"  {call['calldate']} {call['calltime']} | "
                f"{call.get('origin', '?')} -> {call.get('destination', '?')} | "
                f"{call.get('seconds', '?')}s | "
                f"type={call.get('type', '?')} | "
                f"rid={call['RecordingId']}"
            )
        print(
            f"\nTotal calls: {len(all_calls)} across {len(bill_periods)} bill period(s)"
        )
        return

    # Download recordings
    output_dir = Path(args.output_dir)
    downloaded = 0
    for call in recordings:
        result = download_recording(session, call, output_dir, account_code)
        if result:
            downloaded += 1

    print(
        f"\nDownloaded {downloaded}/{len(recordings)} recordings to {output_dir.absolute()}"
    )
    print(
        f"Total calls scanned: {len(all_calls)} across {len(bill_periods)} bill period(s)"
    )


if __name__ == "__main__":
    main()
