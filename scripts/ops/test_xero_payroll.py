#!/usr/bin/env python
"""Diagnose Xero Payroll NZ API 403 errors.

Probes identity connections, the accounting org (including version, edition
and country), then each payroll endpoint separately so one refusal cannot
hide the others.

Reading the results:

- empty-body 403 on ALL payroll endpoints while the accounting probe is OK:
  the payroll product is unprovisioned on the org. Activate it in the Xero
  web UI (see docs/restore-prod-to-nonprod.md).
- 403 with an ``AuthenticationUnsuccessful`` body: tenant drift — the
  token's connections no longer include the configured tenant.
"""

import os
import sys
from pathlib import Path

# scripts/ops/ is two levels below the repo root; see
# scripts/ops/setup_dev_logins.py for why this is inserted explicitly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from xero_python.accounting import AccountingApi  # noqa: E402 -- Django must be configured first
from xero_python.api_client import ApiClient  # noqa: E402
from xero_python.identity import IdentityApi  # noqa: E402
from xero_python.payrollnz import PayrollNzApi  # noqa: E402

from apps.xero.auth import get_api_client, get_tenant_id  # noqa: E402


def probe_accounting(api_client: ApiClient, tenant_id: str) -> None:
    """Probe the accounting org; it should work even without payroll."""
    print("\n--- Accounting API test ---")
    try:
        accounting_api = AccountingApi(api_client)
        orgs = accounting_api.get_organisations(xero_tenant_id=tenant_id)
        if not orgs.organisations:
            print("  FAILED: no organisations returned")
        else:
            org = orgs.organisations[0]
            print(f"  Organisation: {org.name} (version={org.version}, edition={org.edition})")
            print(f"  Country: {org.country_code}")
            print(f"  Shortcode: {org.short_code}")
    except Exception as e:  # noqa: BLE001 -- deliberate-swallow: the accounting probe's pass/fail IS the diagnostic signal; report and keep probing payroll
        print(f"  FAILED: {e}")


def probe_payroll(api_client: ApiClient, tenant_id: str) -> None:
    """Probe each payroll endpoint in its own try.

    One refusal must not hide the others: "all three 403" vs "one 403"
    changes the diagnosis (see module docstring).
    """
    print("\n--- Payroll NZ API test ---")
    payroll_api = PayrollNzApi(api_client)

    print("  get_pay_run_calendars:")
    try:
        calendars_response = payroll_api.get_pay_run_calendars(xero_tenant_id=tenant_id)
        calendars = calendars_response.pay_run_calendars or []
        print(f"    OK: {len(calendars)} calendars")
        for cal in calendars:
            print(f"      - {cal.name} ({cal.calendar_type})")
    except Exception as e:  # noqa: BLE001 -- deliberate-swallow: expected-refusal reporting; the 403 body is the diagnostic payload
        print(f"    FAILED: {e}")

    print("  get_employees:")
    try:
        employees_response = payroll_api.get_employees(xero_tenant_id=tenant_id)
        print(f"    OK: {len(employees_response.employees or [])} employees")
    except Exception as e:  # noqa: BLE001 -- deliberate-swallow: expected-refusal reporting; the 403 body is the diagnostic payload
        print(f"    FAILED: {e}")

    print("  get_earnings_rates:")
    try:
        rates_response = payroll_api.get_earnings_rates(xero_tenant_id=tenant_id)
        print(f"    OK: {len(rates_response.earnings_rates or [])} earnings rates")
    except Exception as e:  # noqa: BLE001 -- deliberate-swallow: expected-refusal reporting; the 403 body is the diagnostic payload
        print(f"    FAILED: {e}")


def main() -> int:
    api_client = get_api_client()

    # List connections, and show the configured tenant beside them so the
    # tenant-drift case (configured id absent from connections) is visible
    # directly in the output.
    identity_api = IdentityApi(api_client)
    connections = identity_api.get_connections()
    print(f"Connected orgs: {len(connections)}")
    for i, c in enumerate(connections):
        print(f"  {i}: {c.tenant_name} (id={c.tenant_id}, type={c.tenant_type})")

    if not connections:
        print("No connections!")
        return 1

    try:
        configured = get_tenant_id()
        print(f"Configured tenant (CompanyDefaults): {configured}")
    except Exception as e:  # noqa: BLE001 -- deliberate-swallow: an unconfigured tenant is one of the states this diagnostic reports, not a reason to stop probing
        print(f"Configured tenant lookup FAILED: {e}")

    tenant_id = connections[0].tenant_id
    tenant_name = connections[0].tenant_name
    if not tenant_id:
        print("First connection has no tenant id!")
        return 1
    print(f"\nUsing: {tenant_name} ({tenant_id})")

    probe_accounting(api_client, tenant_id)
    probe_payroll(api_client, tenant_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
