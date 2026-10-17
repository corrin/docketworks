#!/usr/bin/env python
"""Record OpenAI's answers to ChatKit's domain-key check.

ChatKit's iframe asks ``POST /v1/chatkit/domain_keys/verify`` whether the
configured domain key belongs to the page's origin; nothing else in the chat is
tied to the hostname. A fake-Xero E2E run serves the app on localhost, which no
key is registered for. These recordings answer whether that run can keep the
real check: the registered origin with its key, the local origin with the same
key, and a key OpenAI never issued. Re-run it when the E2E origin or OpenAI's
domain rules change; docs/rewrite-history.md (2026-10-15) holds the ruling.

The key is public (it ships in the page), but the recordings store a marker in
its place so the files stay the same when the key rotates.

Usage:
    uv run python -m scripts.ops.record_chatkit_wire
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict

import requests

from scripts.bootstrap import setup_django

setup_django()

from django.conf import settings  # noqa: E402 -- Django must be configured first

from apps.platform.integrations.models import IntegrationSettings  # noqa: E402

VERIFY_URL = "https://api.openai.com/v1/chatkit/domain_keys/verify"
# The iframe's own origin, as the browser sends it.
IFRAME_ORIGIN = "https://cdn.platform.openai.com"
LOCAL_ORIGIN = "http://localhost:4173"
UNISSUED_KEY = "domain_pk_" + "0" * 48
RECORDINGS_DIR = (
    Path(__file__).resolve().parents[2]
    / "frontend"
    / "tests"
    / "e2e"
    / "fixtures"
    / "chatkit"
    / "recordings"
)


class Case(TypedDict):
    name: str
    referrer_origin: str
    domain_key: str
    key_marker: str


def main() -> int:
    """Ask OpenAI each case once and write one file per answer."""
    configured_key = IntegrationSettings.get_solo().chatkit_domain_key
    if configured_key is None:
        raise SystemExit(
            "No ChatKit domain key on IntegrationSettings; enter it on Admin > Integrations."
        )
    registered_origin = settings.FRONT_END_URL
    if registered_origin == LOCAL_ORIGIN:
        raise SystemExit("FRONT_END_URL is the local origin; run this without run_e2e.sh's export.")
    cases: list[Case] = [
        {
            "name": "registered_origin",
            "referrer_origin": registered_origin,
            "domain_key": configured_key,
            "key_marker": "<configured>",
        },
        {
            "name": "local_origin",
            "referrer_origin": LOCAL_ORIGIN,
            "domain_key": configured_key,
            "key_marker": "<configured>",
        },
        {
            "name": "unissued_key",
            "referrer_origin": registered_origin,
            "domain_key": UNISSUED_KEY,
            "key_marker": "<unissued>",
        },
    ]
    recorded_at = datetime.now(tz=UTC).isoformat(timespec="seconds")
    RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
    for case in cases:
        response = requests.post(
            VERIFY_URL,
            json={"referrer_origin": case["referrer_origin"], "domain_key": case["domain_key"]},
            headers={"Origin": IFRAME_ORIGIN, "Referer": f"{IFRAME_ORIGIN}/"},
            timeout=30,
        )
        document = {
            "recorded_at": recorded_at,
            "request": {
                "method": "POST",
                "url": VERIFY_URL,
                "body": {
                    "referrer_origin": case["referrer_origin"],
                    "domain_key": case["key_marker"],
                },
            },
            "response": {
                "status": response.status_code,
                "content_type": response.headers.get("Content-Type"),
            },
            "body": response.json(),
        }
        target = RECORDINGS_DIR / f"{case['name']}.json"
        target.write_text(json.dumps(document, indent=2) + "\n")
        print(f"  {case['name']:18s} {response.status_code} {response.text[:200]}")
    print(f"Wrote {len(cases)} recordings to {RECORDINGS_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
