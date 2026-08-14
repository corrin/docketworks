#!/usr/bin/env python
"""Fix shop company name after production restore (anonymized during backup)."""

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
NEW_NAME = "Demo Company Shop"


def main() -> int:
    try:
        shop_company = Company.objects.get(id=SHOP_COMPANY_ID)
    except Company.DoesNotExist:
        print(f"ERROR: Shop company with ID {SHOP_COMPANY_ID} not found")
        return 1

    old_name = shop_company.name
    shop_company.name = NEW_NAME
    shop_company.save()

    print("Updated shop company:")
    print(f"  Old name: {old_name}")
    print(f"  New name: {shop_company.name}")
    print(f"  ID: {shop_company.id}")
    print(f"  Job count: {shop_company.jobs.count()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
