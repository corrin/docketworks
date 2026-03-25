#!/usr/bin/env python
"""
Set up employee payroll details for Demo Company.

This script updates EXISTING Xero employees with payroll settings:
- Tax code: M (main employment)
- ESCT rate: 17.5%
- KiwiSaver: active member with 3% employee, 3% employer contributions
- Leave: 160 hours annual leave, 80 hours sick leave per year
- Bank account (pre-validated NZ format)

Note: New employees created via seed_xero_from_database are automatically
set up with these settings. This script is for updating existing employees.

Usage:
    python scripts/setup_demo_payroll.py          # Dry run
    python scripts/setup_demo_payroll.py --execute
"""

import os
import sys
from typing import List

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "docketworks.settings")
import django

django.setup()

from apps.accounts.models import Staff
from apps.timesheet.services.demo_payroll_data import (
    generate_ird_number,
    get_bank_account,
    setup_employee_bank,
    setup_employee_leave,
    setup_employee_tax,
)
from apps.workflow.api.xero.xero import get_tenant_id


def main():
    execute = "--execute" in sys.argv
    print(f"Mode: {'EXECUTE' if execute else 'DRY RUN'}")

    tenant_id = get_tenant_id()
    if not tenant_id:
        print("ERROR: No tenant_id configured")
        return

    staff_list: List[Staff] = list(
        Staff.objects.filter(date_left__isnull=True, xero_user_id__isnull=False)
    )
    print(f"Found {len(staff_list)} staff with Xero IDs")

    if not staff_list:
        return

    results = {"tax": [0, 0], "leave": [0, 0], "bank": [0, 0]}

    for i, staff in enumerate(staff_list):
        ird = generate_ird_number(i + 1)
        bank = get_bank_account(i + 1)
        print(f"{staff.first_name} {staff.last_name}: IRD={ird} Bank={bank}")

        if not execute:
            continue

        # Tax (includes IRD, tax code, ESCT, KiwiSaver)
        try:
            setup_employee_tax(staff.xero_user_id, ird)
            results["tax"][0] += 1
            print(f"  Tax OK: IRD={ird} KiwiSaver=3%/3%")
        except Exception as e:
            results["tax"][1] += 1
            print(f"  ERROR Tax: {e}")

        # Leave entitlements
        try:
            setup_employee_leave(staff.xero_user_id)
            results["leave"][0] += 1
            print("  Leave OK: Annual=160h Sick=80h")
        except Exception as e:
            results["leave"][1] += 1
            print(f"  ERROR Leave: {e}")

        # Bank account
        try:
            setup_employee_bank(staff.xero_user_id, bank)
            results["bank"][0] += 1
            print(f"  Bank OK: {bank}")
        except Exception as e:
            results["bank"][1] += 1
            print(f"  ERROR Bank: {e}")

    if not execute:
        print("\nDRY RUN complete - run with --execute to apply")
    else:
        print(
            f"\nResults: Tax {results['tax'][0]}/{sum(results['tax'])}, "
            f"Leave {results['leave'][0]}/{sum(results['leave'])}, "
            f"Bank {results['bank'][0]}/{sum(results['bank'])}"
        )


if __name__ == "__main__":
    main()
