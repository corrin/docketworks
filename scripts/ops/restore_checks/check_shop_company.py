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

from apps.core.models import CompanyDefaults  # noqa: E402 -- Django must be configured first


def main() -> int:
    # CompanyDefaults.shop_company is the canonical pointer — a hardcoded id
    # would silently miss any installation whose shop row carries another key.
    try:
        shop = CompanyDefaults.get_solo().shop_company
    except CompanyDefaults.DoesNotExist:
        print("ERROR: CompanyDefaults row not found — was the restore loaded?")
        return 1

    print(f"Shop company: {shop.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
