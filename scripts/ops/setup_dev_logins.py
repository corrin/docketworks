#!/usr/bin/env python
"""Create the default admin user and (by default) reset all staff passwords.

The staff-password reset is part of the restore-prod-to-nonprod scrub, where
real prod passwords are replaced with known defaults. Pass --admin-only to
ensure the default admin exists *without* touching staff passwords — that is
what instance creation uses, so provisioning never resets real passwords.
"""

import argparse

from scripts.bootstrap import setup_django

setup_django()

from apps.accounts.models import Staff  # noqa: E402 -- Django must be configured first
from apps.accounts.nonprod_credentials import (  # noqa: E402 -- Django must be configured first
    ADMIN_EMAIL,
    ADMIN_PASSWORD,
    STAFF_PASSWORD,
)
from apps.core.environment import (  # noqa: E402 -- Django must be configured first
    ProductionDatabaseError,
    assert_not_production_database,
)


def refuse_production_database() -> None:
    """Refuse a *_prod target outright, --admin-only included.

    Classification is by the configured database name, matching ADR 0048:
    both passwords this script installs are committed to a public repo, so
    running it against production is a full-staff lockout plus credential
    disclosure in one step. There is no production override flag on purpose —
    production admin access is provisioned by instance onboarding, never by
    this script.
    """
    try:
        assert_not_production_database("this script installs publicly known default passwords.")
    except ProductionDatabaseError as exc:
        raise SystemExit(str(exc)) from exc


def main() -> None:
    refuse_production_database()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--admin-only",
        action="store_true",
        help="Only ensure the default admin exists; do not reset staff passwords.",
    )
    args = parser.parse_args()

    if Staff.objects.filter(office_email=ADMIN_EMAIL).exists():
        print(f"Admin user already exists: {ADMIN_EMAIL}")
    else:
        user = Staff.objects.create_user(
            office_email=ADMIN_EMAIL,
            password=ADMIN_PASSWORD,
            first_name="Default",
            last_name="Admin",
        )
        user.is_office_staff = True
        user.is_superuser = True
        user.save()
        print(f"Created admin user: {user.office_email}")

    if args.admin_only:
        print()
        print("--admin-only: skipping staff password reset (restore-only step).")
        print(f"  Admin: {ADMIN_EMAIL} / {ADMIN_PASSWORD}")
        return

    print()
    print("Resetting all staff passwords...")
    staff_count = 0
    for staff in Staff.objects.exclude(office_email=ADMIN_EMAIL):
        staff.set_password(STAFF_PASSWORD)
        # False, not True: the flag now locks every session to the change
        # screen (apps/core/auth.py), and these logins exist so a dev can act
        # AS a staff member with the printed shared password — flagging them
        # would force each one onto a private password and break the sheet.
        # The gate itself is exercised by its own unit and E2E tests.
        staff.password_needs_reset = False
        staff.save()
        staff_count += 1

    print(f"Reset passwords for {staff_count} staff members.")
    print()
    print("Login credentials:")
    print(f"  Admin: {ADMIN_EMAIL} / {ADMIN_PASSWORD}")
    print(f"  All other staff: their email / {STAFF_PASSWORD}")


if __name__ == "__main__":
    main()
