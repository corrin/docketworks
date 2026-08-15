#!/usr/bin/env python
"""Verify the test company (CompanyDefaults.test_company_name) exists. Read-only."""

import sys

from scripts.bootstrap import setup_django

setup_django()

from apps.company.models import Company  # noqa: E402 -- Django must be configured first
from apps.core.models import CompanyDefaults  # noqa: E402


def main() -> int:
    defaults = CompanyDefaults.get_solo()
    if not defaults.test_company_name:
        print("ERROR: CompanyDefaults.test_company_name is unset")
        return 1

    company = Company.objects.filter(name=defaults.test_company_name).first()
    if not company:
        print(
            f"ERROR: Test company {defaults.test_company_name!r} not found — "
            "run scripts/ops/fix_test_company.py first"
        )
        return 1

    print(f"Test company: {company.name} (ID: {company.id})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
