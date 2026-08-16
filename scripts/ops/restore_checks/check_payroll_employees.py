#!/usr/bin/env python
"""Check that restored staff are linked to payroll employees in THIS organisation.

The failure this exists to catch: a restored production dump gives every
previously-linked staff member a ``xero_user_id`` naming an employee the
connected organisation has never held. Counting non-null ids reports a healthy
number over exactly that state, which is how a fully unlinked payroll survived
a restore — so this gates on the ORGANISATION the id belongs to, not on the id
being present.

Runs after ``seed_xero_from_database``. Before the seed it fails by design:
that is the state the seed exists to repair.
"""

import sys

from scripts.bootstrap import setup_django

setup_django()

from apps.timesheet.services.payroll_employee_sync import (  # noqa: E402 -- Django first
    staff_needing_payroll_link,
)
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
    pending = list(staff_needing_payroll_link(tenant_id))
    if not pending:
        print(f"All staff carrying a payroll employee id are linked to {tenant_id}")
        return 0

    print(f"FAIL: {len(pending)} staff carry an employee id from another organisation:")
    for staff in pending[:10]:
        print(f"  {staff.email}: employee {staff.xero_user_id} in {staff.xero_tenant_id or 'none'}")
    if len(pending) > 10:
        print(f"  ... and {len(pending) - 10} more")
    print("Run: uv run python manage.py seed_xero_from_database --only employees")
    return 1


if __name__ == "__main__":
    sys.exit(main())
