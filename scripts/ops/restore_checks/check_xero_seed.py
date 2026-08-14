#!/usr/bin/env python
"""Verify Xero seed completed successfully."""

import os
import sys
from pathlib import Path

# scripts/ops/restore_checks/ is three levels below the repo root; see
# scripts/ops/setup_dev_logins.py for why this is inserted explicitly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from apps.accounts.models import Staff  # noqa: E402 -- Django must be configured first
from apps.company.models import Company  # noqa: E402
from apps.job.models import Job  # noqa: E402
from apps.purchasing.models import Stock  # noqa: E402


def main() -> None:
    companies_with_xero = Company.objects.filter(xero_contact_id__isnull=False).count()
    jobs_with_xero = Job.objects.filter(xero_project_id__isnull=False).count()
    stock_with_xero = Stock.objects.filter(xero_id__isnull=False, is_active=True).count()
    staff_with_xero = Staff.objects.filter(
        xero_user_id__isnull=False, date_left__isnull=True
    ).count()

    print(f"Companies linked to Xero: {companies_with_xero}")
    print(f"Jobs linked to Xero: {jobs_with_xero}")
    print(f"Stock items synced to Xero: {stock_with_xero}")
    print(f"Staff linked to Xero Payroll: {staff_with_xero}")


if __name__ == "__main__":
    main()
