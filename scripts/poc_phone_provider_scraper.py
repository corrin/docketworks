#!/usr/bin/env python
"""Diagnostic: inspect phone provider CDR rows and download recording samples.

This is not a Celery Beat test harness. Provider deletion must be tested through
the production Celery Beat task path, not through this script.
"""

import argparse
import json
import logging
import os
import sys
from datetime import date, timedelta
from pathlib import Path
from time import sleep
from typing import Any

import requests

LOG = logging.getLogger("phone-provider-diagnostic")

BASE_URL = os.getenv("PHONE_PROVIDER_BASE_URL")
USERNAME = os.getenv("PHONE_PROVIDER_USERNAME")
PASSWORD = os.getenv("PHONE_PROVIDER_PASSWORD")
ACCOUNT_CODE = os.getenv("PHONE_PROVIDER_ACCOUNT_CODE")

if not BASE_URL or not USERNAME or not PASSWORD or not ACCOUNT_CODE:
    print(
        "PHONE_PROVIDER_BASE_URL, PHONE_PROVIDER_USERNAME, "
        "PHONE_PROVIDER_PASSWORD, and PHONE_PROVIDER_ACCOUNT_CODE must be set",
        file=sys.stderr,
    )
    sys.exit(1)

BASE_URL = BASE_URL.rstrip("/")
CDR_ENDPOINT = "/json/account/getCdr"
RECORDING_ENDPOINT = "/account/dlrecording"


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


def login(session: requests.Session) -> None:
    response = session.post(
        f"{BASE_URL}/",
        data={"username": USERNAME, "password": PASSWORD},
        timeout=30,
    )
    if response.status_code != 200 or "/account/status" not in response.url:
        raise RuntimeError(
            f"provider login failed: status={response.status_code} url={response.url}"
        )


def fetch_cdr_page(
    session: requests.Session,
    *,
    page: int,
    start_date: date,
    end_date: date,
) -> list[dict[str, Any]]:
    response = session.post(
        f"{BASE_URL}{CDR_ENDPOINT}",
        data={
            "p": str(page),
            "accountcode": ACCOUNT_CODE,
            "StartDate": start_date.isoformat(),
            "EndDate": end_date.isoformat(),
        },
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, list):
        raise RuntimeError(f"unexpected CDR response type: {type(data)}")
    return data


def iter_calls(
    session: requests.Session,
    *,
    start_date: date,
    end_date: date,
    page_delay: float,
):
    page = 1
    consecutive_empty = 0
    while True:
        rows = fetch_cdr_page(
            session,
            page=page,
            start_date=start_date,
            end_date=end_date,
        )
        if not rows:
            consecutive_empty += 1
            if consecutive_empty >= 2:
                break
            page += 1
            continue
        consecutive_empty = 0
        for row in rows:
            yield row
        page += 1
        if page_delay:
            sleep(page_delay)


def download_recording(session: requests.Session, row: dict[str, Any]) -> bytes:
    response = session.get(
        f"{BASE_URL}{RECORDING_ENDPOINT}",
        params={
            "AccountCode": ACCOUNT_CODE,
            "rid": row["RecordingId"],
            "aparty": row.get("origin", ""),
            "bparty": row.get("destination", ""),
            "date": f"{row['calldate']} - {row['calltime']}",
        },
        timeout=120,
    )
    response.raise_for_status()
    content = response.content
    if content[:3] == b"200":
        content = content[3:].lstrip(b"\r\n ")
    if not content:
        raise RuntimeError(f"recording {row['RecordingId']} returned empty content")
    return content


def recording_filename(row: dict[str, Any]) -> str:
    value = (
        f"{row.get('origin', 'unknown')} - {row.get('destination', 'unknown')}, "
        f"{row['calldate']} - {row['calltime']}.mp3"
    )
    return "".join(
        char if char.isalnum() or char in " .,_-+" else "_" for char in value
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-date", type=date.fromisoformat)
    parser.add_argument("--end-date", type=date.fromisoformat, default=date.today())
    parser.add_argument("--months", type=int)
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--output-dir", default="/tmp/phone-recording-probe")
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

    session = make_session()
    login(session)

    calls = list(
        iter_calls(
            session,
            start_date=start_date,
            end_date=args.end_date,
            page_delay=args.page_delay,
        )
    )
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
        path = output_dir / recording_filename(row)
        if path.exists() and path.stat().st_size:
            print(f"skip existing {path}")
            continue
        payload = download_recording(session, row)
        path.write_bytes(payload)
        downloaded += 1
        print(f"downloaded {row['RecordingId']} {len(payload)} bytes -> {path}")

    print(f"Downloaded {downloaded}/{min(limit, len(recordings))} recordings")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
