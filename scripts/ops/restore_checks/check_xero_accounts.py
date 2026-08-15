#!/usr/bin/env python
"""Check the restored chart of accounts against what the Xero seed requires."""

import sys

from scripts.bootstrap import setup_django

setup_django()

from apps.xero.models import XeroAccount  # noqa: E402 -- Django must be configured first
from apps.xero.seeding import SALES_ACCOUNT_NAME, sales_account_code  # noqa: E402


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
    # NAMED SALES_ACCOUNT_NAME. The rule is not restated here — this calls the
    # seed's own sales_account_code() and prints its refusal, because the
    # restated copy drifted from the original (ADR 0039). Gating on codes 200
    # and 300 instead was rejected — this check runs pre-seed against the
    # PRODUCTION chart, where those codes legitimately do not exist, and every
    # consumer either matches by name (the seed) or falls back by account type
    # (stock sync), so a code gate fails runs that would have succeeded.
    try:
        code = sales_account_code()
    # deliberate-swallow: this script's contract is a FAIL line and exit 1,
    # not a traceback; the refusal text is the operator's instruction.
    except ValueError as exc:
        print(f"FAIL: {exc}")
        return 1

    print(f"Sales account '{SALES_ACCOUNT_NAME}': code {code}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
