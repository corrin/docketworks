#!/usr/bin/env python
"""Verify admin user exists and has correct permissions."""

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

EMAIL = "defaultadmin@example.com"


def main() -> int:
    try:
        user = Staff.objects.get(email=EMAIL)
    except Staff.DoesNotExist:
        print(f"ERROR: User {EMAIL} not found")
        return 1

    print(f"User exists: {user.email}")
    # v1 checked is_active; v2's Staff model has no such field — employment
    # status is date_left-based (StaffManager.currently_active()) instead.
    print(f"Is active (date_left unset): {user.date_left is None}")
    print(f"Is office staff: {user.is_office_staff}")
    print(f"Is superuser: {user.is_superuser}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
