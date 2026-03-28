#!/usr/bin/env python
"""Test script to diagnose Xero Payroll NZ API 403 errors."""

import os
import sys

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "docketworks.settings")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
django.setup()

from xero_python.accounting import AccountingApi
from xero_python.identity import IdentityApi
from xero_python.payrollnz import PayrollNzApi

from apps.workflow.api.xero.xero import api_client


def main():
    # 1. List connections
    identity_api = IdentityApi(api_client)
    connections = identity_api.get_connections()
    print(f"Connected orgs: {len(connections)}")
    for i, c in enumerate(connections):
        print(f"  {i}: {c.tenant_name} (id={c.tenant_id}, type={c.tenant_type})")

    if not connections:
        print("No connections!")
        return

    tenant_id = connections[0].tenant_id
    tenant_name = connections[0].tenant_name
    print(f"\nUsing: {tenant_name} ({tenant_id})")

    # 2. Test accounting API (should work)
    print("\n--- Accounting API test ---")
    try:
        accounting_api = AccountingApi(api_client)
        orgs = accounting_api.get_organisations(xero_tenant_id=tenant_id)
        org = orgs.organisations[0]
        print(
            f"  Organisation: {org.name} (version={org.version}, edition={org.edition})"
        )
        print(f"  Country: {org.country_code}")
        print(f"  Shortcode: {org.short_code}")
    except Exception as e:
        print(f"  FAILED: {e}")

    # 3. Test payroll NZ API
    print("\n--- Payroll NZ API test ---")
    payroll_api = PayrollNzApi(api_client)

    # 3a. Payroll calendars
    print("  get_pay_run_calendars:")
    try:
        response = payroll_api.get_pay_run_calendars(xero_tenant_id=tenant_id)
        print(f"    OK: {len(response.pay_run_calendars or [])} calendars")
        for cal in response.pay_run_calendars or []:
            print(f"      - {cal.name} ({cal.calendar_type})")
    except Exception as e:
        print(f"    FAILED: {e}")

    # 3b. Employees
    print("  get_employees:")
    try:
        response = payroll_api.get_employees(xero_tenant_id=tenant_id)
        print(f"    OK: {len(response.employees or [])} employees")
    except Exception as e:
        print(f"    FAILED: {e}")

    # 3c. Pay items (earnings rates)
    print("  get_earnings_rates:")
    try:
        response = payroll_api.get_earnings_rates(xero_tenant_id=tenant_id)
        print(f"    OK: {len(response.earnings_rates or [])} earnings rates")
    except Exception as e:
        print(f"    FAILED: {e}")


if __name__ == "__main__":
    main()
