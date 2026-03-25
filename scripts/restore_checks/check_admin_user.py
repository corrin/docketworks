#!/usr/bin/env python
"""Verify admin user exists and has correct permissions."""

import os
import sys

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "docketworks.settings")

import django

django.setup()

from apps.accounts.models import Staff

EMAIL = "defaultadmin@example.com"

try:
    user = Staff.objects.get(email=EMAIL)
    print(f"User exists: {user.email}")
    print(f"Is active: {user.is_active}")
    print(f"Is office staff: {user.is_office_staff}")
    print(f"Is superuser: {user.is_superuser}")
except Staff.DoesNotExist:
    print(f"ERROR: User {EMAIL} not found")
    sys.exit(1)
