#!/usr/bin/env python
"""Verify shop company has correct name."""

import os
import sys
from pathlib import Path

# scripts/ops/restore_checks/ is three levels below the repo root; see
# scripts/ops/setup_dev_logins.py for why this is inserted explicitly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from apps.company.models import Company  # noqa: E402 -- Django must be configured first

SHOP_COMPANY_ID = "00000000-0000-0000-0000-000000000001"


def main() -> int:
    try:
        shop = Company.objects.get(id=SHOP_COMPANY_ID)
    except Company.DoesNotExist:
        print(f"ERROR: Shop company with ID {SHOP_COMPANY_ID} not found")
        return 1

    print(f"Shop company: {shop.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
