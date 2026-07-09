"""
E2E Test Data Cleanup

Removes test data created by Playwright E2E tests.
Uses Django ORM for safe FK cascade handling.

Usage:
    python manage.py e2e_cleanup           # Dry run (default)
    python manage.py e2e_cleanup --confirm # Actually delete
"""

import logging

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.accounting.models import Invoice, Quote
from apps.company.models import Company, CompanyPersonLink
from apps.job.models import Job, QuoteSpreadsheet
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLine

logger = logging.getLogger(__name__)

TEST_DATA_PREFIX = "[TEST]"
TEST_COMPANY_NAME = "ABC Carpet Cleaning TEST IGNORE"
LEGACY_E2E_PREFIXES = ["E2E Test Client", "E2E Modal Client", "E2E Test Supplier"]


class Command(BaseCommand):
    help = "Remove E2E test data. Dry run by default, use --confirm to delete."

    def add_arguments(self, parser):
        parser.add_argument(
            "--confirm",
            action="store_true",
            help="Actually delete test data (default is dry run)",
        )

    def handle(self, *args, **options):
        confirm = options["confirm"]

        # Collect what to delete
        test_jobs = Job.objects.filter(name__startswith=TEST_DATA_PREFIX)
        test_people = CompanyPersonLink.objects.filter(
            person__name__startswith=TEST_DATA_PREFIX
        )
        test_companies = Company.objects.filter(name__startswith=TEST_DATA_PREFIX)
        # Swept so Job.company PROTECT doesn't block the [TEST] company delete.
        test_prefix_company_jobs = Job.objects.filter(company__in=test_companies)
        test_prefix_company_people = CompanyPersonLink.objects.filter(
            company__in=test_companies
        )

        # Legacy E2E-prefixed companies and their data
        from django.db.models import Q

        legacy_q = Q()
        for prefix in LEGACY_E2E_PREFIXES:
            legacy_q |= Q(name__startswith=prefix)
        legacy_companies = Company.objects.filter(legacy_q)
        legacy_company_jobs = Job.objects.filter(company__in=legacy_companies)
        legacy_company_people = CompanyPersonLink.objects.filter(
            company__in=legacy_companies
        )

        # Test company data (all jobs/people on the test company are test artifacts)
        test_company_qs = Company.objects.filter(name=TEST_COMPANY_NAME)
        test_company_jobs = Job.objects.filter(company__in=test_company_qs)
        test_company_people = CompanyPersonLink.objects.filter(
            company__in=test_company_qs
        )

        # Report
        self.stdout.write("\n=== E2E Test Data ===\n")

        self._report_queryset("[TEST]-prefixed jobs", test_jobs, "name")
        self._report_queryset("[TEST]-prefixed people", test_people, "person__name")
        self._report_queryset("[TEST]-prefixed companies", test_companies, "name")
        self._report_queryset("Legacy E2E companies", legacy_companies, "name")
        self._report_queryset("Legacy E2E company jobs", legacy_company_jobs, "name")
        self._report_queryset(
            "Legacy E2E company people", legacy_company_people, "person__name"
        )
        self._report_queryset(
            f"Jobs on test company ({TEST_COMPANY_NAME})", test_company_jobs, "name"
        )
        self._report_queryset(
            f"People on test company ({TEST_COMPANY_NAME})",
            test_company_people,
            "person__name",
        )
        self._report_queryset(
            "Jobs on [TEST]-prefixed companies", test_prefix_company_jobs, "name"
        )
        self._report_queryset(
            "People on [TEST]-prefixed companies",
            test_prefix_company_people,
            "person__name",
        )

        total = (
            test_jobs.count()
            + test_people.count()
            + test_companies.count()
            + legacy_companies.count()
            + legacy_company_jobs.count()
            + legacy_company_people.count()
            + test_company_jobs.count()
            + test_company_people.count()
            + test_prefix_company_jobs.count()
            + test_prefix_company_people.count()
        )

        if total == 0:
            self.stdout.write("\nNo test data found. Database is clean.")
            return

        if not confirm:
            self.stdout.write("\n=== DRY RUN — no changes made ===")
            self.stdout.write(
                "Run with --confirm to delete:\n"
                "  python manage.py e2e_cleanup --confirm"
            )
            return

        # Sync sequences first — SimpleHistory post_delete signals need working sequences.
        self.stdout.write("\nSyncing sequences...")
        from django.core.management import call_command

        call_command("sync_sequences")
        self.stdout.write("Sequences synced.")

        # Collect all jobs that will be deleted (union of all sources)
        all_jobs_to_delete = (
            test_jobs
            | test_company_jobs
            | legacy_company_jobs
            | test_prefix_company_jobs
        ).distinct()

        # Check for rows with PROTECTED FKs pointing at these jobs
        linked_invoices = Invoice.objects.filter(job__in=all_jobs_to_delete)
        linked_quotes = Quote.objects.filter(job__in=all_jobs_to_delete)
        linked_po_lines = PurchaseOrderLine.objects.filter(job__in=all_jobs_to_delete)
        linked_quote_sheets = QuoteSpreadsheet.objects.filter(
            job__in=all_jobs_to_delete
        )

        if linked_invoices.exists():
            self._report_queryset(
                "Invoices linked to test jobs (will be deleted)",
                linked_invoices,
                "number",
            )
        if linked_quotes.exists():
            self._report_queryset(
                "Quotes linked to test jobs (will be deleted)",
                linked_quotes,
                "number",
            )
        if linked_po_lines.exists():
            self._report_queryset(
                "PO lines linked to test jobs (will be deleted)",
                linked_po_lines,
                "description",
            )
        if linked_quote_sheets.exists():
            self._report_queryset(
                "Quote spreadsheets linked to test jobs (will be deleted)",
                linked_quote_sheets,
                "sheet_id",
            )

        # Collect all companies to delete
        all_companies_to_delete = (test_companies | legacy_companies).distinct()

        # Find POs referencing these companies (PROTECTED FK on supplier)
        linked_pos = PurchaseOrder.objects.filter(supplier__in=all_companies_to_delete)

        if linked_pos.exists():
            self._report_queryset(
                "Purchase orders linked to test companies (will be deleted)",
                linked_pos,
                "id",
            )

        # Delete in correct order — PROTECTED FKs first, then cascading.
        self.stdout.write("\nDeleting...")

        # Atomic so a mid-run failure can't leave half-deleted test data.
        with transaction.atomic():
            # 1. Invoices on test jobs (PROTECTED FK)
            count, details = linked_invoices.delete()
            if count:
                self.stdout.write(f"  Invoices: {count} objects ({details})")

            # 2. POs on test companies (PROTECTED FK on supplier)
            count, details = linked_pos.delete()
            if count:
                self.stdout.write(f"  Purchase orders: {count} objects ({details})")

            # 3. Other PROTECTED dependents of test jobs
            count, details = linked_quotes.delete()
            if count:
                self.stdout.write(f"  Quotes: {count} objects ({details})")

            count, details = linked_po_lines.delete()
            if count:
                self.stdout.write(f"  PO lines: {count} objects ({details})")

            count, details = linked_quote_sheets.delete()
            if count:
                self.stdout.write(f"  Quote spreadsheets: {count} objects ({details})")

            # 4. Jobs on test company (cascade deletes cost sets, cost lines, etc.)
            count, details = test_company_jobs.delete()
            self.stdout.write(f"  Test company jobs: {count} objects ({details})")

            # 5. People on test company
            count, details = test_company_people.delete()
            self.stdout.write(f"  Test company people: {count} objects ({details})")

            # 6. Legacy company data
            count, details = legacy_company_jobs.delete()
            self.stdout.write(f"  Legacy company jobs: {count} objects ({details})")

            count, details = legacy_company_people.delete()
            self.stdout.write(f"  Legacy company people: {count} objects ({details})")

            count, details = legacy_companies.delete()
            self.stdout.write(f"  Legacy companies: {count} objects ({details})")

            # 7. [TEST]-prefixed items (may overlap with above, that's fine)
            count, details = test_jobs.delete()
            self.stdout.write(f"  [TEST] jobs: {count} objects ({details})")

            count, details = test_people.delete()
            self.stdout.write(f"  [TEST] people: {count} objects ({details})")

            # 8. Jobs/people on [TEST]-prefixed companies (unblocks company delete)
            count, details = test_prefix_company_jobs.delete()
            self.stdout.write(
                f"  Jobs on [TEST] companies: {count} objects ({details})"
            )

            count, details = test_prefix_company_people.delete()
            self.stdout.write(
                f"  People on [TEST] companies: {count} objects ({details})"
            )

            count, details = test_companies.delete()
            self.stdout.write(f"  [TEST] companies: {count} objects ({details})")

        self.stdout.write("\nDone.")

    def _report_queryset(self, label, qs, field):
        count = qs.count()
        if count == 0:
            return
        self.stdout.write(f"\n  {label} ({count}):")
        for obj in qs.order_by(field).values_list(field, flat=True)[:20]:
            self.stdout.write(f"    - {obj}")
        if count > 20:
            self.stdout.write(f"    ... and {count - 20} more")
