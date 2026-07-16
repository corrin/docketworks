#!/usr/bin/env python
"""
Push database companies to Xero as contacts.

This script is designed to run after production restore and Xero sync.
It finds companies that are referenced by jobs or purchase orders but don't
have xero_contact_id values, and creates them as contacts in Xero.

Usage:
    python scripts/push_companies_to_xero.py [--dry-run] [--force]

Options:
    --dry-run   Show what would be created without making changes
    --force     Skip confirmation prompt (for automated runs)

This ensures development Xero tenant has all the contacts needed for realistic testing.
"""

import os
import sys

import django
from django.conf import settings
from django.db import transaction

# Setup Django
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "docketworks.settings")
django.setup()

from apps.company.models import Company
from apps.workflow.api.xero.sync import sync_company_to_xero
from apps.workflow.services.error_persistence import persist_app_error


def get_database_name():
    """Get the current database name for safety checks."""
    return settings.DATABASES["default"]["NAME"]


def confirm_operation(force=False, dry_run=False):
    """Confirm this operation before proceeding."""
    db_name = get_database_name()

    # Safety check - never run on production database
    if "prod" in db_name.lower() or "production" in db_name.lower():
        print(f"❌ ERROR: Refusing to run on production database: {db_name}")
        print("This script is only for development databases.")
        sys.exit(1)

    print(f"🔍 Database: {db_name}")
    if dry_run:
        print("🔍 DRY RUN mode - no changes will be made")
    else:
        print("⚠️  This will CREATE contacts in your Xero development tenant")
    print()

    if force and not dry_run:
        print("⚡ Force mode enabled - skipping confirmation")
        print()
        return

    if dry_run:
        print("Proceeding with dry run...")
        print()
        return

    response = input("Proceed? (yes/no): ").strip().lower()
    if response not in ["yes", "y"]:
        print("Operation cancelled.")
        sys.exit(0)
    print()


def find_companies_to_push():
    """Find companies that need to be pushed to Xero."""
    # Companies referenced by jobs
    companies_with_jobs = Company.objects.filter(
        jobs__isnull=False, xero_contact_id__isnull=True
    ).distinct()

    # Companies referenced by purchase orders
    companies_with_pos = Company.objects.filter(
        purchase_orders__isnull=False, xero_contact_id__isnull=True
    ).distinct()

    # Combine and deduplicate
    all_companies = (
        (companies_with_jobs | companies_with_pos).distinct().order_by("name")
    )

    return all_companies


def push_companies_to_xero(companies, dry_run=False):
    """Push companies to Xero and track results."""
    results = {"success": [], "failed": [], "skipped": []}

    for i, company in enumerate(companies, 1):
        print(f"📤 ({i}/{len(companies)}) Processing: {company.name}")

        # Validate company has required data
        try:
            if not company.validate_for_xero():
                print("  ⚠️  Skipping - missing required data for Xero")
                results["skipped"].append((company, "Missing required data"))
                continue
        except Exception as e:
            print(f"  ❌ Validation error: {e}")
            results["failed"].append((company, f"Validation error: {e}"))
            continue

        if dry_run:
            print(f"  ✅ Would create contact: {company.name}")
            results["success"].append((company, "Would create (dry run)"))
            continue

        # Attempt to push to Xero
        try:
            success = sync_company_to_xero(company)
            if success:
                print(f"  ✅ Created in Xero with ID: {company.xero_contact_id}")
                results["success"].append((company, company.xero_contact_id))
            else:
                print("  ❌ Failed to create in Xero")
                results["failed"].append(
                    (company, "sync_company_to_xero returned False")
                )
        except Exception as e:
            print(f"  ❌ Error creating in Xero: {e}")
            persist_app_error(
                e,
                additional_context={
                    "operation": "push_companies_to_xero",
                    "company_id": str(company.id),
                    "company_name": company.name,
                },
            )
            results["failed"].append((company, str(e)))

    return results


def main():
    """Main execution function."""
    # Parse command line arguments
    dry_run = "--dry-run" in sys.argv
    force = "--force" in sys.argv

    mode_text = "DRY RUN - " if dry_run else ""
    print(f"🚀 {mode_text}Push Database Companies to Xero")
    print("=" * 50)

    # Safety confirmation
    confirm_operation(force=force, dry_run=dry_run)

    # Find companies that need to be pushed
    print("🔍 Finding companies that need to be pushed to Xero...")
    companies_to_push = find_companies_to_push()

    if not companies_to_push:
        print("✅ No companies need to be pushed to Xero.")
        print(
            "All companies with jobs or purchase orders already have xero_contact_id values."
        )
        return

    print(f"📋 Found {len(companies_to_push)} companies to push:")
    for company in companies_to_push[:10]:  # Show first 10
        job_count = company.jobs.count()
        po_count = company.purchase_orders.count()
        print(f"  • {company.name} (Jobs: {job_count}, POs: {po_count})")

    if len(companies_to_push) > 10:
        print(f"  ... and {len(companies_to_push) - 10} more")

    print()

    # Push companies to Xero
    action_text = "Simulating push of" if dry_run else "Pushing"
    print(f"🚀 {action_text} {len(companies_to_push)} companies to Xero...")
    print()

    with transaction.atomic():
        results = push_companies_to_xero(companies_to_push, dry_run=dry_run)

    # Report results
    print()
    print("✅ COMPLETED")
    print("-" * 30)
    print(f"✅ Success: {len(results['success'])}")
    print(f"❌ Failed: {len(results['failed'])}")
    print(f"⚠️  Skipped: {len(results['skipped'])}")

    if results["failed"]:
        print()
        print("❌ Failed companies:")
        for company, reason in results["failed"]:
            print(f"  • {company.name}: {reason}")

    if results["skipped"]:
        print()
        print("⚠️  Skipped companies:")
        for company, reason in results["skipped"]:
            print(f"  • {company.name}: {reason}")

    if not dry_run and results["success"]:
        print()
        print("💡 Next steps:")
        print("  1. Verify contacts created in Xero web interface")
        print("  2. Test Xero Projects sync with created contacts")

    print()
    if dry_run:
        print("🔍 Dry run complete - no changes made")
        print("Run without --dry-run to actually create contacts in Xero")
    else:
        print("🎉 Company push to Xero complete!")


if __name__ == "__main__":
    main()
