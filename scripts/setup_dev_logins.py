#!/usr/bin/env python
"""Create the default admin user and (by default) reset all staff passwords.

The staff-password reset is part of the restore-prod-to-nonprod scrub, where
real prod passwords are replaced with known defaults. Pass --admin-only to
ensure the default admin exists *without* touching staff passwords — that is
what instance creation uses, so provisioning never resets real passwords.
"""

import argparse
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "docketworks.settings")

import django

django.setup()

from apps.accounts.models import Staff

ADMIN_EMAIL = "defaultadmin@example.com"
ADMIN_PASSWORD = "Default-admin-password"
STAFF_PASSWORD = "Default-staff-password"

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument(
    "--admin-only",
    action="store_true",
    help="Only ensure the default admin exists; do not reset staff passwords.",
)
args = parser.parse_args()

# Create or update admin user
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
else:
    # Reset all staff passwords to default
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
