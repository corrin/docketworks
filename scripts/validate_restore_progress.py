#!/usr/bin/env python
"""
Validate restore progress and enforce critical step order.
This script ensures Xero OAuth is completed before testing steps.
"""

import os
import sys

import django

# Setup Django
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "docketworks.settings")
django.setup()

from apps.accounts.models import Staff
from apps.client.models import Client
from apps.job.models import Job
from apps.workflow.models import CompanyDefaults, XeroToken


def check_basic_restore():
    """Check if basic restore steps (1-16) are complete."""
    checks = []

    # Check database has data
    job_count = Job.objects.count()
    staff_count = Staff.objects.count()
    client_count = Client.objects.count()

    checks.append(
        (
            "Database populated",
            job_count > 0 and staff_count > 0 and client_count > 0,
            f"Jobs: {job_count}, Staff: {staff_count}, Clients: {client_count}",
        )
    )

    # Check company defaults
    try:
        company = CompanyDefaults.get_solo()
        checks.append(
            (
                "Company defaults loaded",
                company.company_name == "Demo Company",
                f"Company: {company.company_name}",
            )
        )
    except Exception:
        checks.append(("Company defaults loaded", False, "Not found"))

    # Check admin user
    admin_exists = Staff.objects.filter(
        email="defaultadmin@example.com", is_superuser=True
    ).exists()
    checks.append(
        (
            "Admin user created",
            admin_exists,
            "defaultadmin@example.com exists" if admin_exists else "Not found",
        )
    )

    # Check shop client
    shop_exists = Client.objects.filter(
        id="00000000-0000-0000-0000-000000000001"
    ).exists()
    checks.append(
        (
            "Shop client exists",
            shop_exists,
            "Shop client found" if shop_exists else "Not found",
        )
    )

    return checks


def check_xero_oauth():
    """Check if Xero OAuth is completed (Step 17)."""
    # XeroToken exists and has required fields means OAuth is complete
    active_token = XeroToken.objects.filter(
        access_token__isnull=False, refresh_token__isnull=False
    ).exists()
    return active_token


def check_xero_config():
    """Check if Xero configuration is complete (Steps 18-21)."""
    checks = []

    # Check tenant ID
    try:
        company = CompanyDefaults.get_solo()
        has_tenant = bool(company.xero_tenant_id)
        checks.append(
            (
                "Xero tenant ID set",
                has_tenant,
                "Tenant ID configured" if has_tenant else "Not set",
            )
        )
    except Exception:
        checks.append(("Xero tenant ID set", False, "Company defaults not found"))

    # Check if Xero IDs are cleared (they should be null or have new IDs)
    clients_with_xero = Client.objects.filter(xero_contact_id__isnull=False).count()
    jobs_with_xero = Job.objects.filter(xero_project_id__isnull=False).count()

    checks.append(
        (
            "Xero sync status",
            True,
            f"Clients with Xero ID: {clients_with_xero}, Jobs with Xero ID: {jobs_with_xero}",
        )
    )

    return checks


def validate_restore_state(allow_testing=False):
    """
    Validate the current restore state and enforce step order.

    Args:
        allow_testing: If True, check if testing steps are allowed

    Returns:
        tuple: (is_valid, message)
    """
    print("=" * 60)
    print("RESTORE PROCESS VALIDATION")
    print("=" * 60)

    # Check basic restore
    print("\n📋 BASIC RESTORE (Steps 1-16):")
    basic_checks = check_basic_restore()
    basic_complete = all(check[1] for check in basic_checks)

    for name, passed, detail in basic_checks:
        status = "✅" if passed else "❌"
        print(f"  {status} {name}: {detail}")

    if not basic_complete:
        print("\n❌ CRITICAL: Basic restore incomplete!")
        print("   Complete steps 1-16 before proceeding.")
        return False, "Basic restore incomplete"

    # Check Xero OAuth
    print("\n🔐 XERO OAUTH (Step 17):")
    xero_connected = check_xero_oauth()

    if xero_connected:
        print("  ✅ Xero OAuth token found - Connected to Xero")
    else:
        print("  ❌ No active Xero token found!")
        print("\n" + "=" * 60)
        print("🚨 CRITICAL: XERO OAUTH NOT COMPLETED!")
        print("=" * 60)
        print("\nYou MUST complete Step 17 before proceeding:")
        print("1. Navigate to http://localhost:8000")
        print("2. Login with: defaultadmin@example.com / Default-admin-password")
        print("3. Go to Xero menu > Connect to Xero")
        print("4. Complete the OAuth flow")
        print("\n❌ DO NOT PROCEED to any further steps until this is complete!")

        if allow_testing:
            return False, "Xero OAuth required before testing"
        return False, "Xero OAuth not completed"

    # Check Xero configuration
    print("\n⚙️  XERO CONFIGURATION (Steps 18-21):")
    xero_checks = check_xero_config()
    xero_configured = all(check[1] for check in xero_checks)

    for name, passed, detail in xero_checks:
        status = "✅" if passed else "⚠️"
        print(f"  {status} {name}: {detail}")

    if not xero_configured and allow_testing:
        print("\n⚠️  Warning: Xero configuration incomplete")
        print("   Complete steps 18-21 for full Xero integration")

    # Summary
    print("\n" + "=" * 60)
    if allow_testing:
        if xero_connected:
            print("✅ TESTING ALLOWED - Xero OAuth completed")
            print("   You may proceed with steps 22-24")
            return True, "Testing allowed"
        else:
            print("❌ TESTING FORBIDDEN - Complete Xero OAuth first!")
            return False, "Xero OAuth required"
    else:
        if xero_connected:
            print("✅ Ready to proceed with Xero configuration (Steps 18-21)")
            return True, "Ready for Xero config"
        else:
            print("❌ Must complete Xero OAuth before continuing")
            return False, "Xero OAuth required"


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Validate restore progress")
    parser.add_argument(
        "--allow-testing",
        action="store_true",
        help="Check if testing steps (22-24) are allowed",
    )
    args = parser.parse_args()

    is_valid, message = validate_restore_state(allow_testing=args.allow_testing)

    if not is_valid:
        sys.exit(1)
