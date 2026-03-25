#!/usr/bin/env python
"""Set up development login credentials: create admin user and reset all staff passwords."""

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "docketworks.settings")

import django

django.setup()

from apps.accounts.models import Staff

ADMIN_EMAIL = "defaultadmin@example.com"
ADMIN_PASSWORD = "Default-admin-password"
STAFF_PASSWORD = "Default-staff-password"

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
