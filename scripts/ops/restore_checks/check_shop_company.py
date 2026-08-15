#!/usr/bin/env python
"""Verify shop company has correct name."""

import sys

from scripts.bootstrap import setup_django

setup_django()

from apps.core.models import CompanyDefaults  # noqa: E402 -- Django must be configured first
from scripts.ops.restore_checks.fix_shop_company import (  # noqa: E402 -- Django must be configured first
    NEW_NAME,
)


def main() -> int:
    # CompanyDefaults.shop_company is the canonical pointer — a hardcoded id
    # would silently miss any installation whose shop row carries another key.
    try:
        shop = CompanyDefaults.get_solo().shop_company
    except CompanyDefaults.DoesNotExist:
        print("ERROR: CompanyDefaults row not found — was the restore loaded?")
        return 1

    print(f"Shop company: {shop.name}")
    # The check loop runs after fix_shop_company, so the repaired name is the
    # required state — passing on any name would green-light a restore whose
    # shop repair never ran.
    if shop.name != NEW_NAME:
        print(
            f"ERROR: shop company is named {shop.name!r}, expected {NEW_NAME!r} — "
            "run scripts/ops/restore_checks/fix_shop_company.py"
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
