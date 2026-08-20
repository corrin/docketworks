#!/usr/bin/env python
"""Gate: restored staff are linked to payroll employees in THIS organisation.

The failure this exists to catch: a restored production dump gives every
previously-linked staff member a ``xero_user_id`` naming an employee the
connected organisation has never held. Counting non-null ids reports a healthy
number over exactly that state, which is how a fully unlinked payroll survived
a restore — so this gates on the ORGANISATION the id belongs to, not on the id
being present.

``verify_`` and not ``check_`` on purpose. The runbook's post-restore loop
globs ``check_*.py`` and runs it BEFORE Xero is reconnected and seeded, where
every check in it is expected to pass. This one cannot pass there — there is no
connected organisation yet and no staff are linked, which is precisely the
state the seed exists to repair — so putting it in that glob would halt the
restore at a step that was working. It belongs after the seed, and the prefix
is what keeps it there.
"""

import sys

from scripts.bootstrap import setup_django

setup_django()

from apps.accounts.models import Staff  # noqa: E402 -- Django must be configured first
from apps.timesheet.services.payroll_employee_sync import staff_needing_payroll_link  # noqa: E402
from apps.xero.auth import get_tenant_id  # noqa: E402


def main() -> int:
    tenant_id = get_tenant_id()
    if not tenant_id:
        print("FAIL: no Xero organisation is connected; run manage.py xero --setup first")
        return 1

    # The seed's own predicate, called rather than restated: a second copy of
    # "which staff still need linking" is free to disagree with the one the
    # phase works from, and then this check passes over work not done
    # (ADR 0039).
    linked = Staff.objects.filter(xero_user_id__isnull=False, xero_tenant_id=tenant_id).count()
    pending = list(staff_needing_payroll_link(tenant_id))
    print(f"Staff linked to payroll employees in {tenant_id}: {linked}")
    if not pending:
        print("All staff carrying a payroll employee id are linked to this organisation")
        return 0

    print(f"FAIL: {len(pending)} staff carry an employee id from another organisation:")
    for staff in pending[:10]:
        print(
            f"  {staff.office_email}: employee {staff.xero_user_id} "
            f"in {staff.xero_tenant_id or 'none'}"
        )
    if len(pending) > 10:
        print(f"  ... and {len(pending) - 10} more")
    print("Run: uv run python manage.py seed_xero_from_database --only employees")
    return 1


if __name__ == "__main__":
    sys.exit(main())
