"""Remove data created by Playwright E2E tests.

The command is a dry run unless ``--confirm`` is supplied. Cross-domain
cleanup belongs in diagnostics, which sits above the domain-app layer; putting
it in core would invert the import contract merely for an operator tool.
"""

from typing import Any

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandParser
from django.db import transaction
from django.db.models import Model, Q, QuerySet

from apps.accounting.models import Invoice, Quote
from apps.company.models import Company, CompanyPersonLink, Person
from apps.job.models import Job, QuoteSpreadsheet
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLine

TEST_COMPANY_NAME = "ABC Carpet Cleaning TEST IGNORE"
TEST_DATA_PREFIX = "[TEST]"
LEGACY_E2E_PREFIXES = ("E2E Test Client", "E2E Modal Client", "E2E Test Supplier")


class Command(BaseCommand):
    """Report or remove E2E-created rows in dependency-safe order."""

    help = "Remove E2E test data. Dry run by default; use --confirm to delete."

    def add_arguments(self, parser: CommandParser) -> None:
        """Add the explicit destructive-operation confirmation flag."""
        parser.add_argument(
            "--confirm",
            action="store_true",
            help="Actually delete test data (default is dry run)",
        )

    def handle(  # noqa: PLR0915 -- deletion ordering is the command's safety contract
        self, *_args: Any, **options: Any
    ) -> None:
        """Report matching rows, then delete them atomically when confirmed."""
        confirm = bool(options["confirm"])

        test_jobs = Job.objects.filter(name__startswith=TEST_DATA_PREFIX)
        test_people = CompanyPersonLink.objects.filter(person__name__startswith=TEST_DATA_PREFIX)
        test_person_records = Person.objects.filter(name__startswith=TEST_DATA_PREFIX)
        test_companies = Company.objects.filter(name__startswith=TEST_DATA_PREFIX)
        test_prefix_company_jobs = Job.objects.filter(company__in=test_companies)
        test_prefix_company_people = CompanyPersonLink.objects.filter(company__in=test_companies)

        legacy_q = Q()
        for prefix in LEGACY_E2E_PREFIXES:
            legacy_q |= Q(name__startswith=prefix)
        legacy_companies = Company.objects.filter(legacy_q)
        legacy_company_jobs = Job.objects.filter(company__in=legacy_companies)
        legacy_company_people = CompanyPersonLink.objects.filter(company__in=legacy_companies)

        test_company = Company.objects.filter(name=TEST_COMPANY_NAME)
        test_company_jobs = Job.objects.filter(company__in=test_company)
        test_company_people = CompanyPersonLink.objects.filter(company__in=test_company)

        self.stdout.write("\n=== E2E Test Data ===\n")
        self._report_queryset("[TEST]-prefixed jobs", test_jobs, "name")
        self._report_queryset("[TEST]-prefixed people", test_people, "person__name")
        self._report_queryset(
            "Underlying [TEST]-prefixed person records", test_person_records, "name"
        )
        self._report_queryset("[TEST]-prefixed companies", test_companies, "name")
        self._report_queryset("Legacy E2E companies", legacy_companies, "name")
        self._report_queryset("Legacy E2E company jobs", legacy_company_jobs, "name")
        self._report_queryset("Legacy E2E company people", legacy_company_people, "person__name")
        self._report_queryset(
            f"Jobs on test company ({TEST_COMPANY_NAME})", test_company_jobs, "name"
        )
        self._report_queryset(
            f"People on test company ({TEST_COMPANY_NAME})",
            test_company_people,
            "person__name",
        )
        self._report_queryset("Jobs on [TEST]-prefixed companies", test_prefix_company_jobs, "name")
        self._report_queryset(
            "People on [TEST]-prefixed companies",
            test_prefix_company_people,
            "person__name",
        )

        total = sum(
            queryset.count()
            for queryset in (
                test_jobs,
                test_people,
                test_person_records,
                test_companies,
                legacy_companies,
                legacy_company_jobs,
                legacy_company_people,
                test_company_jobs,
                test_company_people,
                test_prefix_company_jobs,
                test_prefix_company_people,
            )
        )
        if total == 0:
            self.stdout.write("\nNo test data found. Database is clean.")
            return
        if not confirm:
            self.stdout.write("\n=== DRY RUN — no changes made ===")
            self.stdout.write(
                "Run with --confirm to delete:\n  python manage.py e2e_cleanup --confirm"
            )
            return

        all_companies = (test_companies | legacy_companies).distinct()
        all_people_links = (
            test_company_people | legacy_company_people | test_people | test_prefix_company_people
        ).distinct()
        people_ids = set(all_people_links.values_list("person_id", flat=True)) | set(
            test_person_records.values_list("id", flat=True)
        )
        all_jobs = (
            test_jobs | test_company_jobs | legacy_company_jobs | test_prefix_company_jobs
        ).distinct()

        linked_invoices = Invoice.objects.filter(job__in=all_jobs)
        linked_quotes = Quote.objects.filter(job__in=all_jobs)
        linked_po_lines = PurchaseOrderLine.objects.filter(job__in=all_jobs)
        linked_quote_sheets = QuoteSpreadsheet.objects.filter(job__in=all_jobs)
        linked_pos = PurchaseOrder.objects.filter(supplier__in=all_companies)

        self.stdout.write("\nSyncing sequences...")
        call_command("sync_sequences")
        self.stdout.write("Sequences synced.\n\nDeleting...")

        with transaction.atomic():
            self._delete_queryset("Invoices", linked_invoices)
            self._delete_queryset("Purchase orders", linked_pos)
            self._delete_queryset("Quotes", linked_quotes)
            self._delete_queryset("PO lines", linked_po_lines)
            self._delete_queryset("Quote spreadsheets", linked_quote_sheets)
            self._delete_queryset("Test company jobs", test_company_jobs)
            self._delete_queryset("Test company people", test_company_people)
            self._delete_queryset("Legacy company jobs", legacy_company_jobs)
            self._delete_queryset("Legacy company people", legacy_company_people)
            self._delete_queryset("Legacy companies", legacy_companies)
            self._delete_queryset("[TEST] jobs", test_jobs)
            self._delete_queryset("[TEST] people", test_people)
            self._delete_queryset("Jobs on [TEST] companies", test_prefix_company_jobs)
            self._delete_queryset("People on [TEST] companies", test_prefix_company_people)

            remaining_person_ids = CompanyPersonLink.objects.exclude(
                company__in=all_companies
            ).values_list("person_id", flat=True)
            orphaned_test_people = Person.objects.filter(id__in=people_ids).exclude(
                id__in=remaining_person_ids
            )
            self._delete_queryset("Underlying test person records", orphaned_test_people)
            self._delete_queryset("[TEST] companies", test_companies)

        self.stdout.write("\nDone.")

    def _report_queryset(self, label: str, queryset: QuerySet[Model], field: str) -> None:
        """Print a bounded preview of one deletion category."""
        count = queryset.count()
        if count == 0:
            return
        self.stdout.write(f"\n  {label} ({count}):")
        for value in queryset.order_by(field).values_list(field, flat=True)[:20]:
            self.stdout.write(f"    - {value}")
        if count > 20:
            self.stdout.write(f"    ... and {count - 20} more")

    def _delete_queryset(self, label: str, queryset: QuerySet[Model]) -> None:
        """Delete one category and report Django's cascade details."""
        count, details = queryset.delete()
        self.stdout.write(f"  {label}: {count} objects ({details})")
