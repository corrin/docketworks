#!/usr/bin/env python
"""Create the test company (CompanyDefaults.test_company_name) when missing.

Idempotent restore-time mutation. Pairs with
scripts/ops/restore_checks/check_test_company.py, which is read-only.
"""

import os
import sys
from pathlib import Path

# See scripts/ops/setup_dev_logins.py for why this is needed for a direct
# `python scripts/ops/fix_test_company.py` invocation to find "config"/"apps".
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from django.utils import timezone  # noqa: E402 -- Django must be configured first

from apps.company.models import Company  # noqa: E402
from apps.core.models import CompanyDefaults  # noqa: E402


def main() -> None:
    defaults = CompanyDefaults.get_solo()
    if not defaults.test_company_name:
        raise RuntimeError(
            "CompanyDefaults.test_company_name is unset; set it before running this script."
        )

    company = Company.objects.filter(name=defaults.test_company_name).first()

    if company:
        print(f"Test company already exists: {company.name} (ID: {company.id})")
        return

    company = Company(
        name=defaults.test_company_name,
        is_account_customer=False,
        xero_last_modified=timezone.now(),
        xero_last_synced=timezone.now(),
    )
    company.save()
    print(f"Created test company: {company.name} (ID: {company.id})")


if __name__ == "__main__":
    main()
