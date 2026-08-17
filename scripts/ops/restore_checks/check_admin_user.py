#!/usr/bin/env python
"""Verify admin user exists and has correct permissions."""

import sys

from scripts.bootstrap import setup_django

setup_django()

from apps.accounts.models import Staff  # noqa: E402 -- Django must be configured first

EMAIL = "defaultadmin@example.com"


def main() -> int:
    try:
        user = Staff.objects.get(office_email=EMAIL)
    except Staff.DoesNotExist:
        print(f"ERROR: User {EMAIL} not found")
        return 1

    print(f"User exists: {user.office_email}")
    # v1 checked is_active; v2's Staff model has no such field — employment
    # status is date_left-based (StaffManager.currently_active()) instead.
    print(f"Is active (date_left unset): {user.date_left is None}")
    print(f"Is office staff: {user.is_office_staff}")
    print(f"Is superuser: {user.is_superuser}")
    # A check that prints a bad state but exits 0 lets the check loop pass
    # with an unusable admin — each requirement fails the run.
    failures = 0
    if user.date_left is not None:
        print("ERROR: default admin has date_left set (not an active staff member)")
        failures += 1
    if not user.is_office_staff:
        print("ERROR: default admin is not office staff")
        failures += 1
    if not user.is_superuser:
        print("ERROR: default admin is not a superuser")
        failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
