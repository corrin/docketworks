"""Remove data created by Playwright E2E tests.

The command is a dry run unless ``--confirm`` is supplied. Cross-domain
cleanup belongs in diagnostics, which sits above the domain-app layer; putting
it in core would invert the import contract merely for an operator tool.

Everything a spec creates through the app exists in the Xero demo organisation
too — a contact per company, and the invoices, quotes and purchase orders
raised against it — and the local rows are the only record of which Xero
objects those are. So a confirmed run removes them from Xero FIRST and only
then deletes locally, because the delete erases the ids the removal needs.

Fable: driven from the local rows, never from a query against the
organisation. The rejected alternative is asking Xero what looks like E2E
residue, which is ``e2e_xero_sweep``'s job and a different question: this
command answers "undo what this database's run did", and reading the answer
off the rows that run wrote means the two can never disagree. It also means a
hard-killed run is still covered — its dirty database is still sitting there,
still naming every Xero id it created.

A company already archived in Xero is the organisation's mirror, not residue,
and is left alone here and by the E2E preflight. With no local rows there is
nothing to remove in Xero either; reach for ``e2e_xero_sweep`` when the
organisation holds residue this database has forgotten.

E2E-seeded phone calls are recognised by a ``[TEST]`` description, like every
other row a run creates. A call has no name to prefix, and its job and company
links are SET_NULL, so a seeded call outlives both and cannot be found through
them. Its recording is also a file on disk, which deleting the row does not
remove.
"""

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction
from django.db.models import Model, Q, QuerySet

from apps.accounting.models import Invoice, Quote
from apps.company.models import Company, CompanyPersonLink, Person
from apps.core.models import CompanyDefaults
from apps.core.test_data import (
    LEGACY_E2E_PREFIXES,
    TEST_COMPANY_NAME,
    TEST_DATA_PREFIX,
)
from apps.crm.models import PhoneCallRecord, PhoneCallRecording
from apps.crm.services.phone_call_service import delete_local_recording
from apps.diagnostics.services.e2e_xero_residue import (
    RemovalOutcome,
    XeroResidue,
    remove_residue_from_xero,
)
from apps.job.models import Job, QuoteSpreadsheet
from apps.process.models import Form, FormEntry, Procedure
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLine, Stock, StockMovement


class Command(BaseCommand):
    """Report or remove E2E-created rows in dependency-safe order, and archive their contacts."""

    help = (
        "Remove E2E test data locally and archive its Xero contacts. "
        "Dry run by default; use --confirm to act."
    )

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
        confirm = options["confirm"]
        if not isinstance(confirm, bool):
            raise TypeError("The confirm option must be a boolean")

        test_jobs = Job.objects.filter(name__startswith=TEST_DATA_PREFIX)
        test_people = CompanyPersonLink.objects.filter(person__name__startswith=TEST_DATA_PREFIX)
        test_person_records = Person.objects.filter(name__startswith=TEST_DATA_PREFIX)
        # Fable: dependants are matched by the company's NAME whatever its Xero
        # status — a job or PO a spec raised against a now-archived company is
        # still residue — while the company row itself is deleted only when
        # not archived in Xero, since an archived one is the organisation's
        # mirror and would only be re-imported.
        named_test_companies = Company.objects.filter(name__startswith=TEST_DATA_PREFIX)
        test_companies = named_test_companies.filter(xero_archived=False)
        test_prefix_company_jobs = Job.objects.filter(company__in=named_test_companies)
        test_prefix_company_people = CompanyPersonLink.objects.filter(
            company__in=named_test_companies
        )

        legacy_q = Q()
        for prefix in LEGACY_E2E_PREFIXES:
            legacy_q |= Q(name__startswith=prefix)
        named_legacy_companies = Company.objects.filter(legacy_q)
        legacy_companies = named_legacy_companies.filter(xero_archived=False)
        legacy_company_jobs = Job.objects.filter(company__in=named_legacy_companies)
        legacy_company_people = CompanyPersonLink.objects.filter(company__in=named_legacy_companies)

        test_company = Company.objects.filter(name=TEST_COMPANY_NAME)

        # The named test company is seed data, not test residue: specs select
        # it by name and CompanyDefaults.test_company_name documents that it is
        # preserved during backports. Its E2E-created jobs and people are
        # removed by the [TEST] name match above; the company row itself must
        # survive.
        #
        # Opus: matching this company's dependants by foreign key instead was
        # rejected. all_jobs drives the Xero invoice and quote deletions, and a
        # Xero deletion is not something the database restore undoes, so a
        # hand-made ordinarily-named job on this company would lose its Xero
        # documents. The E2E preflight (checkSafeToTest) counts only
        # [TEST]-named rows and could not have warned about one either. Every
        # row a spec creates carries the prefix, so the name match loses
        # nothing and leaves the preflight asking the same question this
        # command answers.
        deletable_companies = (test_companies | legacy_companies).distinct()
        named_companies = (named_test_companies | named_legacy_companies).distinct()
        all_people_links = (
            test_people | test_prefix_company_people | legacy_company_people
        ).distinct()
        all_jobs = (test_jobs | test_prefix_company_jobs | legacy_company_jobs).distinct()

        self.stdout.write("\n=== E2E Test Data ===\n")
        self._report_queryset("[TEST]-prefixed jobs", test_jobs, "name")
        self._report_queryset("[TEST]-prefixed people", test_people, "person__name")
        self._report_queryset(
            "Underlying [TEST]-prefixed person records", test_person_records, "name"
        )
        self._report_queryset(
            "[TEST]-prefixed companies (not archived in Xero)", test_companies, "name"
        )
        self._report_queryset(
            "Legacy E2E companies (not archived in Xero)", legacy_companies, "name"
        )
        self._report_queryset("Named E2E test company", test_company, "name")
        self._report_queryset("Legacy E2E company jobs", legacy_company_jobs, "name")
        self._report_queryset("Legacy E2E company people", legacy_company_people, "person__name")
        self._report_queryset("Jobs on [TEST]-prefixed companies", test_prefix_company_jobs, "name")
        self._report_queryset(
            "People on [TEST]-prefixed companies",
            test_prefix_company_people,
            "person__name",
        )

        # Invoices and quotes PROTECT on company as well as job, so a
        # company-scoped row with job=None would abort the whole transaction
        # if only job-scoped rows were removed first.
        linked_invoices = Invoice.objects.filter(
            Q(job__in=all_jobs) | Q(company__in=named_companies)
        )
        linked_quotes = Quote.objects.filter(Q(job__in=all_jobs) | Q(company__in=named_companies))
        linked_po_lines = PurchaseOrderLine.objects.filter(job__in=all_jobs)
        linked_quote_sheets = QuoteSpreadsheet.objects.filter(job__in=all_jobs)
        linked_pos = PurchaseOrder.objects.filter(supplier__in=named_companies)

        # A receipt turns an order line into stock, and the inventory ledger
        # protects what it records (ADR 0058): the stock row protects its
        # order line, every movement protects its stock, and a reversal
        # protects the movement it reverses. So a run that receipted anything
        # leaves a purchase order nothing can delete, which is what stranded
        # the teardown after it had already removed the order from Xero.
        # Scoped by the ORDER as well as the job: stock received to the
        # workshop rather than to a job has no job to be found through.
        run_po_lines = PurchaseOrderLine.objects.filter(
            Q(purchase_order__in=linked_pos) | Q(job__in=all_jobs)
        )
        run_stock = Stock.objects.filter(source_purchase_order_line__in=run_po_lines)
        run_movements = StockMovement.objects.filter(stock__in=run_stock)
        reversing_movements = run_movements.filter(reverses__isnull=False)

        # The description is the whole rule. Matching on the call's job or
        # company instead would miss every call whose job and company have
        # already been set to NULL, and would sweep the standing test
        # company's real calls, which are live data.
        e2e_calls = PhoneCallRecord.objects.filter(description__startswith=TEST_DATA_PREFIX)
        archived_recordings = PhoneCallRecording.objects.filter(call__in=e2e_calls).exclude(
            storage_path__isnull=True
        )
        self._report_queryset("E2E phone calls", e2e_calls, "description")
        self._report_queryset(
            "E2E phone recordings with a local file",
            archived_recordings,
            "provider_recording_id",
        )

        # ProcessEvent CASCADEs from both form and form_entry, so it needs no
        # queryset of its own here. Acknowledgement CASCADEs from form (and,
        # slice 2, procedure) the same way.
        test_form_entries = FormEntry.objects.filter(form__title__startswith=TEST_DATA_PREFIX)
        test_forms = Form.objects.filter(title__startswith=TEST_DATA_PREFIX)
        test_procedures = Procedure.objects.filter(title__startswith=TEST_DATA_PREFIX)
        self._report_queryset("E2E process form entries", test_form_entries, "form__title")
        self._report_queryset("E2E process forms", test_forms, "title")
        self._report_queryset("E2E process procedures", test_procedures, "title")

        total = sum(
            queryset.count()
            for queryset in (
                all_jobs,
                all_people_links,
                test_person_records,
                deletable_companies,
                linked_invoices,
                linked_quotes,
                linked_pos,
                e2e_calls,
                test_form_entries,
                test_forms,
                test_procedures,
            )
        )

        residue = self._collect_residue(
            deletable_companies, linked_invoices, linked_quotes, linked_pos
        )
        self._report_residue(residue)

        if not confirm:
            if total == 0:
                self.stdout.write("\nNo local test data found.")
            self.stdout.write("\n=== DRY RUN — no changes made ===")
            self.stdout.write(
                "Run with --confirm to act:\n  python manage.py e2e_cleanup --confirm"
            )
            return

        if total == 0:
            self.stdout.write("\nNo local test data found. Database is clean.")
            return

        people_ids = set(all_people_links.values_list("person_id", flat=True)) | set(
            test_person_records.values_list("id", flat=True)
        )

        # Before the Xero removal, not after: this refusal means the matched
        # companies look like production data, and removing their documents
        # from the organisation first would be the destruction it exists to
        # prevent.
        self._refuse_protected_company_references(deletable_companies)

        # Xero before the local delete, which erases the ids the removal needs.
        self._report_removal(remove_residue_from_xero(residue, "e2e_cleanup"))

        self.stdout.write("\nDeleting...")

        with transaction.atomic():
            # Files first, and inside the transaction: a rollback then leaves
            # rows whose file is gone, which the download endpoint already
            # answers with 404 and the next --confirm finishes. Deleting the
            # files after the commit instead would orphan files that no run
            # can find, because the rows naming them would be gone.
            for recording in archived_recordings:
                delete_local_recording(recording)
            self._delete_queryset("E2E phone calls", e2e_calls)

            self._delete_queryset("Invoices", linked_invoices)
            # Reversals before the movements they reverse, movements before
            # the stock they record, stock before the order line it came
            # from: each step frees the next.
            self._delete_queryset("Reversing stock movements", reversing_movements)
            self._delete_queryset("Stock movements", run_movements)
            self._delete_queryset("Receipted stock", run_stock)
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

            self._delete_queryset("E2E process form entries", test_form_entries)
            self._delete_queryset("E2E process forms", test_forms)
            self._delete_queryset("E2E process procedures", test_procedures)

        # After the deletes so the sequences reflect the final table state.
        self.stdout.write("\nSyncing sequences...")
        call_command("sync_sequences")
        self.stdout.write("Sequences synced.\n\nDone.")

    def _collect_residue(
        self,
        companies: QuerySet[Company],
        invoices: QuerySet[Invoice],
        quotes: QuerySet[Quote],
        purchase_orders: QuerySet[PurchaseOrder],
    ) -> XeroResidue:
        """Collect the Xero ids these local rows carry.

        A purchase order or company with no id was never pushed — a draft
        order, a prospect that has not reached Xero — and the organisation
        holds nothing to remove for it.
        """
        return XeroResidue(
            # Invoice.xero_id and Quote.xero_id are NOT NULL: a row exists only
            # because Xero answered a create, so there is no unpushed case to
            # filter. PurchaseOrder.xero_id and Company.xero_contact_id are
            # nullable and the filters below are that difference, not guards.
            invoices={str(invoice.xero_id): invoice.number for invoice in invoices},
            # Quotes are labelled by their Xero id, not their number: the
            # number column is nullable, and a label that is sometimes absent
            # is worse in a refusal line than one that is always the value you
            # would paste into Xero anyway.
            quotes={str(quote.xero_id): str(quote.xero_id) for quote in quotes},
            purchase_orders={
                str(order.xero_id): order.po_number
                for order in purchase_orders
                if order.xero_id is not None
            },
            contacts={
                company.xero_contact_id: company.name
                for company in companies
                if company.xero_contact_id
            },
        )

    def _report_residue(self, residue: XeroResidue) -> None:
        """Print what the run left in the organisation, before touching it."""
        self.stdout.write("\n=== E2E residue in Xero ===")
        if residue.is_empty():
            self.stdout.write("  Nothing: no local row names a Xero object.")
            return
        for label, entries in (
            ("Invoices to delete", residue.invoices),
            ("Quotes to delete", residue.quotes),
            ("Purchase orders to delete", residue.purchase_orders),
            ("Contacts to archive", residue.contacts),
        ):
            if entries:
                self.stdout.write(f"  {label}: {len(entries)}")

    def _report_removal(self, outcome: RemovalOutcome) -> None:
        """Print what Xero accepted and what it refused."""
        for kind, count in outcome.removed.items():
            self.stdout.write(self.style.SUCCESS(f"  Xero: removed {count} {kind}(s)."))
        for refusal in outcome.refused:
            # Reported, not raised. Xero declines to remove a document past the
            # state it allows removing from, which no cleanup can undo, and
            # failing here would strand every later run on one spec's leftover.
            self.stdout.write(
                self.style.WARNING(
                    f"  Xero refused {refusal.kind} {refusal.label}: {refusal.reason}"
                )
            )

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
