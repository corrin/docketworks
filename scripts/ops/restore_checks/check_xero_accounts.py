#!/usr/bin/env python
"""Verify chart of accounts synced from Xero."""

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


def main() -> None:
    print(f"Total accounts synced: {XeroAccount.objects.count()}")

    sales = XeroAccount.objects.filter(account_code="200").first()
    purchases = XeroAccount.objects.filter(account_code="300").first()

    print(f"Sales account (200): {sales.account_name if sales else 'NOT FOUND'}")
    print(f"Purchases account (300): {purchases.account_name if purchases else 'NOT FOUND'}")


if __name__ == "__main__":
    main()
