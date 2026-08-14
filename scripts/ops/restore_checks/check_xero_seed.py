#!/usr/bin/env python
"""Report what the Xero seed linked, for an operator to read.

Informational by design: it prints counts and exits zero whatever they are.
There is no threshold to gate on — how many companies, stock items or staff
SHOULD carry a Xero id depends entirely on the dataset that was restored.
"""

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
    # Always 0 today, and that is the correct reading: the clear phase nulls
    # every xero_project_id and the projects phase that would repopulate them
    # is a Phase 4 deferral (Xero Projects is unported). Kept rather than
    # deleted because the line becomes meaningful the day that phase lands.
    print(f"Jobs linked to Xero Projects (unported, expect 0): {jobs_with_xero}")
    print(f"Stock items synced to Xero: {stock_with_xero}")
    # Counts staff carrying a production employee link the clear phase
    # preserved, not staff linked in the target org: the employees phase is
    # the same Phase 4 deferral.
    print(f"Staff carrying a Xero Payroll employee id: {staff_with_xero}")


if __name__ == "__main__":
    main()
