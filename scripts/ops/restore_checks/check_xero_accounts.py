#!/usr/bin/env python
"""Check the restored chart of accounts against what the Xero seed requires."""

import os
import sys
from pathlib import Path

# scripts/ops/restore_checks/ is three levels below the repo root; see
# scripts/ops/setup_dev_logins.py for why this is inserted explicitly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from apps.xero.models import XeroAccount  # noqa: E402 -- Django must be configured first
from apps.xero.seeding import SALES_ACCOUNT_NAME  # noqa: E402


def main() -> int:
    print(f"Total accounts synced: {XeroAccount.objects.count()}")

    # Informational, never a gate: 200 and 300 are Xero's DEFAULT chart codes.
    # A demo organisation has them; a real chart of accounts need not, and
    # MSM's production chart codes purchases 394 with no 300 at all.
    code_200 = XeroAccount.objects.filter(account_code="200").first()
    code_300 = XeroAccount.objects.filter(account_code="300").first()
    print(f"Account code 200: {code_200.account_name if code_200 else 'absent'}")
    print(f"Account code 300: {code_300.account_name if code_300 else 'absent'}")
    if code_300 is None:
        print("  stock sync falls back to the first EXPENSE/DIRECTCOSTS account by code")

    # The seed's one hard requirement on the chart, and so the only thing this
    # gates on: every seeded invoice and quote line is coded to the account
    # NAMED SALES_ACCOUNT_NAME (apps/xero/seeding.py). Gating on codes 200 and
    # 300 instead was rejected — this check runs pre-seed against the
    # PRODUCTION chart, where those codes legitimately do not exist, and every
    # consumer either matches by name (the seed) or falls back by account type
    # (stock sync), so a code gate fails runs that would have succeeded.
    sales = XeroAccount.objects.filter(account_name=SALES_ACCOUNT_NAME).first()
    if sales is None:
        print(
            f"FAIL: no XeroAccount named '{SALES_ACCOUNT_NAME}'. The seed codes every invoice "
            f"and quote line to that account and cannot run without it."
        )
        return 1
    if not sales.account_code:
        print(
            f"FAIL: the '{SALES_ACCOUNT_NAME}' account has no account_code. Set it to the "
            f"organisation's sales revenue code before seeding."
        )
        return 1

    print(f"Sales account '{SALES_ACCOUNT_NAME}': code {sales.account_code}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
