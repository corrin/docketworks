"""Remove data created by Playwright E2E tests.

The command is a dry run unless ``--confirm`` is supplied. Cross-domain
cleanup belongs in diagnostics, which sits above the domain-app layer; putting
it in core would invert the import contract merely for an operator tool.
"""

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction
from django.db.models import Model, Q, QuerySet

from apps.accounting.models import Invoice, Quote
from apps.company.models import Company, CompanyPersonLink, Person
from apps.core.models import CompanyDefaults
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
        self, *_args: object, **options: object
    ) -> None:
        """Report matching rows, then delete them atomically when confirmed."""
        confirm_option = options.get("confirm")
        if not isinstance(confirm_option, bool):
            raise TypeError("The confirm option must be a boolean")
        confirm = confirm_option

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

        # The named test company is seed data, not test residue: specs select
        # it by name and CompanyDefaults.test_company_name documents that it is
        # preserved during backports. Its E2E-created jobs and people are
        # removed; the company row itself must survive.
        deletable_companies = (test_companies | legacy_companies).distinct()
        all_people_links = (
            test_people | test_prefix_company_people | legacy_company_people | test_company_people
        ).distinct()
        all_jobs = (
            test_jobs | test_prefix_company_jobs | legacy_company_jobs | test_company_jobs
        ).distinct()

        self.stdout.write("\n=== E2E Test Data ===\n")
        self._report_queryset("[TEST]-prefixed jobs", test_jobs, "name")
        self._report_queryset("[TEST]-prefixed people", test_people, "person__name")
        self._report_queryset(
            "Underlying [TEST]-prefixed person records", test_person_records, "name"
        )
        self._report_queryset("[TEST]-prefixed companies", test_companies, "name")
        self._report_queryset("Legacy E2E companies", legacy_companies, "name")
        self._report_queryset("Named E2E test company", test_company, "name")
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
            for queryset in (all_jobs, all_people_links, test_person_records, deletable_companies)
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

        people_ids = set(all_people_links.values_list("person_id", flat=True)) | set(
            test_person_records.values_list("id", flat=True)
        )

        # Invoices and quotes PROTECT on company as well as job, so a
        # company-scoped row with job=None would abort the whole transaction
        # if only job-scoped rows were removed first.
        linked_invoices = Invoice.objects.filter(
            Q(job__in=all_jobs) | Q(company__in=deletable_companies)
        )
        linked_quotes = Quote.objects.filter(
            Q(job__in=all_jobs) | Q(company__in=deletable_companies)
        )
        linked_po_lines = PurchaseOrderLine.objects.filter(job__in=all_jobs)
        linked_quote_sheets = QuoteSpreadsheet.objects.filter(job__in=all_jobs)
        linked_pos = PurchaseOrder.objects.filter(supplier__in=deletable_companies)

        self._refuse_protected_company_references(deletable_companies)

        self.stdout.write("\nDeleting...")

        with transaction.atomic():
            self._delete_queryset("Invoices", linked_invoices)
            self._delete_queryset("Purchase orders", linked_pos)
            self._delete_queryset("Quotes", linked_quotes)
            self._delete_queryset("PO lines", linked_po_lines)
            self._delete_queryset("Quote spreadsheets", linked_quote_sheets)
            self._delete_queryset("E2E jobs", all_jobs)
            self._delete_queryset("E2E company people", all_people_links)

            remaining_person_ids = CompanyPersonLink.objects.exclude(
                company__in=deletable_companies
            ).values_list("person_id", flat=True)
            orphaned_test_people = Person.objects.filter(id__in=people_ids).exclude(
                id__in=remaining_person_ids
            )
            self._delete_queryset("Underlying test person records", orphaned_test_people)
            self._delete_queryset("E2E companies", deletable_companies)

        # After the deletes so the sequences reflect the final table state.
        self.stdout.write("\nSyncing sequences...")
        call_command("sync_sequences")
        self.stdout.write("Sequences synced.\n\nDone.")

    def _refuse_protected_company_references(self, companies: QuerySet[Company]) -> None:
        """Refuse deletion when a company holds PROTECT references not cleaned here.

        Quoting scraper data or being the shop company can only mean an
        E2E-named company is really production data;
        deleting around them would be destroying evidence, so name the blocker
        and stop before the transaction rather than rolling it back opaquely.
        """
        blockers: list[str] = []
        shop_companies = CompanyDefaults.objects.filter(shop_company__in=companies)
        if shop_companies.exists():
            blockers.append("CompanyDefaults.shop_company points at a company matched for deletion")
        quoting_relations = (
            "supplier_credentials",
            "scraper_config",
            "scraped_products",
            "price_lists",
            "scrape_jobs",
        )
        for relation in quoting_relations:
            referenced = companies.filter(**{f"{relation}__isnull": False}).distinct()
            for name in referenced.values_list("name", flat=True):
                blockers.append(f"{name} has quoting {relation} rows (PROTECT)")
        if blockers:
            details = "\n  - ".join(blockers)
            raise CommandError(
                "Refusing to delete: companies matched for E2E cleanup carry "
                f"references this command does not remove:\n  - {details}\n"
                "These names look like production data. Resolve them by hand."
            )

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
