#!/usr/bin/env python
"""Create the default admin user and (by default) reset all staff passwords.

The staff-password reset is part of the restore-prod-to-nonprod scrub, where
real prod passwords are replaced with known defaults. Pass --admin-only to
ensure the default admin exists *without* touching staff passwords — that is
what instance creation uses, so provisioning never resets real passwords.
"""

import argparse
import os
import sys
from pathlib import Path

# scripts/ops/ is two levels below the repo root; a direct `python
# scripts/ops/setup_dev_logins.py` invocation (the documented dw-run.sh usage)
# only puts this file's own directory on sys.path, not the root "config" and
# "apps" packages live under. Insert it explicitly rather than requiring every
# caller to know to run this as `-m scripts.ops.setup_dev_logins`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from django.conf import settings  # noqa: E402 -- Django must be configured first

from apps.accounts.models import Staff  # noqa: E402 -- Django must be configured first
from apps.core.environment import database_class  # noqa: E402 -- Django must be configured first

ADMIN_EMAIL = "defaultadmin@example.com"
ADMIN_PASSWORD = "Default-admin-password"  # noqa: S105 -- known nonprod default, not a live secret
STAFF_PASSWORD = "Default-staff-password"  # noqa: S105 -- known nonprod default, not a live secret


def refuse_production_database() -> None:
    """Refuse a *_prod target outright, --admin-only included.

    Classification is by the configured database name, matching ADR 0048:
    both passwords this script installs are committed to a public repo, so
    running it against production is a full-staff lockout plus credential
    disclosure in one step. There is no production override flag on purpose —
    production admin access is provisioned by instance onboarding, never by
    this script.
    """
    db_name = str(settings.DATABASES["default"]["NAME"])
    if database_class(db_name) == "prod":
        raise SystemExit(
            f"Refusing to run against production database {db_name!r}: this script "
            "installs publicly known default passwords."
        )


def main() -> None:
    refuse_production_database()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--admin-only",
        action="store_true",
        help="Only ensure the default admin exists; do not reset staff passwords.",
    )
    args = parser.parse_args()

    if Staff.objects.filter(email=ADMIN_EMAIL).exists():
        print(f"Admin user already exists: {ADMIN_EMAIL}")
    else:
        user = Staff.objects.create_user(
            email=ADMIN_EMAIL,
            password=ADMIN_PASSWORD,
            first_name="Default",
            last_name="Admin",
        )
        user.is_office_staff = True
        user.is_superuser = True
        user.save()
        print(f"Created admin user: {user.email}")

    if args.admin_only:
        print()
        print("--admin-only: skipping staff password reset (restore-only step).")
        print(f"  Admin: {ADMIN_EMAIL} / {ADMIN_PASSWORD}")
        return

    print()
    print("Resetting all staff passwords...")
    staff_count = 0
    for staff in Staff.objects.exclude(email=ADMIN_EMAIL):
        staff.set_password(STAFF_PASSWORD)
        staff.password_needs_reset = True
        staff.save()
        staff_count += 1

    print(f"Reset passwords for {staff_count} staff members.")
    print()
    print("Login credentials:")
    print(f"  Admin: {ADMIN_EMAIL} / {ADMIN_PASSWORD}")
    print(f"  All other staff: their email / {STAFF_PASSWORD}")


if __name__ == "__main__":
    main()
