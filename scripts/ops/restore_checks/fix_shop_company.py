#!/usr/bin/env python
"""Fix shop company name after production restore (anonymized during backup)."""

import sys

from scripts.bootstrap import setup_django

setup_django()

from apps.core.models import CompanyDefaults  # noqa: E402 -- Django must be configured first

NEW_NAME = "Demo Company Shop"


def main() -> int:
    # CompanyDefaults.shop_company is the canonical pointer — a hardcoded id
    # would silently miss any installation whose shop row carries another key.
    try:
        shop_company = CompanyDefaults.get_solo().shop_company
    except CompanyDefaults.DoesNotExist:
        print("ERROR: CompanyDefaults row not found — was the restore loaded?")
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
