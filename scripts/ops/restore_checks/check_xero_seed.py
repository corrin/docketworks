#!/usr/bin/env python
"""Report what the Xero seed linked, for an operator to read.

Informational by design: it prints counts and exits zero whatever they are.
There is no threshold to gate on — how many companies, stock items or staff
SHOULD carry a Xero id depends entirely on the dataset that was restored.
"""

from scripts.bootstrap import setup_django

setup_django()

from apps.accounts.models import Staff  # noqa: E402 -- Django must be configured first
from apps.company.models import Company  # noqa: E402
from apps.job.models import Job  # noqa: E402
from apps.purchasing.models import Stock  # noqa: E402
from apps.xero.auth import get_tenant_id  # noqa: E402


def main() -> None:
    companies_with_xero = Company.objects.filter(xero_contact_id__isnull=False).count()
    jobs_with_xero = Job.objects.filter(xero_project_id__isnull=False).count()
    stock_with_xero = Stock.objects.filter(xero_id__isnull=False, is_active=True).count()
    staff_with_xero = Staff.objects.filter(
        xero_user_id__isnull=False, date_left__isnull=True
    ).count()
    staff_linked_here = Staff.objects.filter(
        xero_user_id__isnull=False,
        date_left__isnull=True,
        xero_tenant_id=get_tenant_id(),
    ).count()

    print(f"Companies linked to Xero: {companies_with_xero}")
    # Always 0 today, and that is the correct reading: the clear phase nulls
    # every xero_project_id and the projects phase that would repopulate them
    # is a Phase 4 deferral (Xero Projects is unported). Kept rather than
    # deleted because the line becomes meaningful the day that phase lands.
    print(f"Jobs linked to Xero Projects (unported, expect 0): {jobs_with_xero}")
    print(f"Stock items synced to Xero: {stock_with_xero}")
    # Both numbers, because the first one alone is what let a completely
    # unlinked payroll read as healthy: a restored dump carries a production
    # employee id on every previously-linked staff member, and the clear phase
    # preserves it. Only the second says anything about THIS organisation, and
    # check_payroll_employees.py is the gate on it.
    print(f"Staff carrying a Xero Payroll employee id: {staff_with_xero}")
    print(f"  of those, linked to the connected organisation: {staff_linked_here}")


if __name__ == "__main__":
    main()
