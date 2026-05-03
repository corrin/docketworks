import logging
import socket
import time
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection
from dotenv import load_dotenv
from xero_python.accounting import AccountingApi
from xero_python.accounting.models import Contact as XeroContact
from xero_python.accounting.models import Invoice as XeroInvoice
from xero_python.accounting.models import LineItem
from xero_python.accounting.models import Quote as XeroQuote

from apps.accounting.models import Invoice, Quote
from apps.accounts.models import Staff
from apps.client.models import Client
from apps.job.models import Job
from apps.purchasing.models import Stock
from apps.timesheet.services.payroll_employee_sync import PayrollEmployeeSyncService
from apps.workflow.api.xero.auth import api_client, get_tenant_id
from apps.workflow.api.xero.seed import (
    fetch_xero_entity_lookup,
    seed_clients_to_xero,
    seed_jobs_to_xero,
)
from apps.workflow.api.xero.stock_sync import sync_all_local_stock_to_xero
from apps.workflow.api.xero.transforms import process_xero_data
from apps.workflow.models import CompanyDefaults, XeroAccount
from apps.workflow.views.xero.xero_helpers import (
    clean_payload,
    convert_to_pascal_case,
    format_date,
    sanitize_for_xero,
)

load_dotenv()

logger = logging.getLogger("xero")


class Command(BaseCommand):
    help = "Seed Xero development tenant with database clients and jobs"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be synced without making changes",
        )
        parser.add_argument(
            "--only",
            type=str,
            help="Sync specific entities only. Comma-separated: accounts,contacts,projects,invoices,stock,employees",
        )
        parser.add_argument(
            "--skip-clear",
            action="store_true",
            help="Skip clearing production Xero IDs (useful for re-running after partial failure)",
        )

    VALID_ENTITIES = {
        "accounts",
        "contacts",
        "projects",
        "invoices",
        "quotes",
        "stock",
        "employees",
    }

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        only_arg = options["only"]
        skip_clear = options["skip_clear"]

        # Parse entities to sync
        if only_arg is None:
            entities_to_sync = self.VALID_ENTITIES.copy()
        else:
            entities_to_sync = {e.strip().lower() for e in only_arg.split(",")}
            invalid = entities_to_sync - self.VALID_ENTITIES
            if invalid:
                raise ValueError(
                    f"Invalid entities: {invalid}. Valid: {self.VALID_ENTITIES}"
                )

        mode_text = "DRY RUN - " if dry_run else ""
        only_text = f" (only: {sorted(entities_to_sync)})" if only_arg else ""
        self.stdout.write(f"{mode_text}Seeding Xero from Database{only_text}")
        self.stdout.write("=" * 50)

        accounts_processed = 0
        contacts_processed = 0
        projects_processed = 0
        invoices_result = {"created": 0, "orphans_deleted": 0}
        quotes_result = {"created": 0, "orphans_deleted": 0}
        stock_processed = 0
        employees_result = {"linked": 0, "created": 0, "already_linked": 0}

        # Clear production Xero IDs (unless skipped)
        if not skip_clear:
            self.stdout.write("Clearing Production Xero IDs...")
            self.clear_production_xero_ids(dry_run)

        # Sync accounts (updates prod xero_ids to dev values)
        if "accounts" in entities_to_sync:
            self.stdout.write("Syncing Accounts...")
            accounts_processed = self.process_accounts(dry_run)

        # Sync contacts
        if "contacts" in entities_to_sync:
            self.stdout.write("Syncing Contacts...")
            contacts_processed = self.process_contacts(dry_run)

        # Sync projects (only if enabled in settings)
        if "projects" in entities_to_sync:
            if settings.XERO_SYNC_PROJECTS:
                self.stdout.write("Syncing Projects...")
                projects_processed = self.process_projects(dry_run)
            else:
                self.stdout.write("Skipping Projects (XERO_SYNC_PROJECTS is disabled)")

        # Sync payroll employees (run before invoices/quotes/stock so payroll
        # is in place before any financial transactions are seeded)
        if "employees" in entities_to_sync:
            self.stdout.write("Syncing Payroll Employees...")
            employees_result = self.process_employees(dry_run)

        # Sync invoices (requires contacts to be seeded first)
        if "invoices" in entities_to_sync:
            self.stdout.write("Syncing Invoices...")
            invoices_result = self.process_invoices(dry_run)

        # Sync quotes (requires contacts to be seeded first)
        if "quotes" in entities_to_sync:
            self.stdout.write("Syncing Quotes...")
            quotes_result = self.process_quotes(dry_run)

        # Sync stock items
        if "stock" in entities_to_sync:
            self.stdout.write("Syncing Stock Items...")
            stock_processed = self.process_stock_items(dry_run)

        # Summary
        self.stdout.write("COMPLETED")
        self.stdout.write(f"Accounts processed: {accounts_processed}")
        self.stdout.write(f"Contacts processed: {contacts_processed}")
        self.stdout.write(f"Projects processed: {projects_processed}")
        self.stdout.write(
            f"Employees linked: {employees_result['linked']}, "
            f"created: {employees_result['created']}, "
            f"already linked: {employees_result['already_linked']}"
        )
        self.stdout.write(
            f"Invoices: {invoices_result['created']} created, "
            f"{invoices_result['orphans_deleted']} orphans deleted"
        )
        self.stdout.write(
            f"Quotes: {quotes_result['created']} created, "
            f"{quotes_result['orphans_deleted']} orphans deleted"
        )
        self.stdout.write(f"Stock items processed: {stock_processed}")

        if dry_run:
            self.stdout.write("Dry run complete - no changes made")
        else:
            # Enable Xero sync now that prod IDs are cleared and dev IDs are seeded
            company = CompanyDefaults.get_solo()
            company.enable_xero_sync = True
            company.save()
            self.stdout.write("Xero seeding complete! enable_xero_sync is now True.")

    def process_accounts(self, dry_run):
        """Phase 0: Update XeroAccount xero_ids from prod to dev Xero tenant.

        The backup includes XeroAccount records with prod xero_id values.
        Dev Xero has the same accounts (same names/codes) but different xero_ids.
        Fetch accounts from dev Xero and upsert by account_name to update xero_ids.
        """
        local_count = XeroAccount.objects.count()
        self.stdout.write(f"Found {local_count} XeroAccount records from backup")

        if local_count == 0:
            self.stdout.write("No XeroAccount records to update")
            return 0

        if dry_run:
            self.stdout.write("Would fetch accounts from dev Xero and update xero_ids")
            return local_count

        xero_api = AccountingApi(api_client)
        xero_tenant_id = get_tenant_id()

        response = xero_api.get_accounts(xero_tenant_id)
        xero_accounts = response.accounts or []
        self.stdout.write(f"Fetched {len(xero_accounts)} accounts from dev Xero")

        updated = 0
        created = 0
        for account in xero_accounts:
            _, was_created = XeroAccount.objects.update_or_create(
                account_name=account.name,
                defaults={
                    "xero_id": account.account_id,
                    "account_code": account.code,
                    "description": getattr(account, "description", None),
                    "account_type": account.type,
                    "tax_type": account.tax_type,
                    "enable_payments": getattr(
                        account, "enable_payments_to_account", False
                    ),
                    "xero_last_modified": account._updated_date_utc,
                    "xero_last_synced": None,
                    "raw_json": process_xero_data(account),
                },
            )
            if was_created:
                created += 1
            else:
                updated += 1

        self.stdout.write(f"Accounts Summary: {updated} updated, {created} created")
        return updated + created

    def process_contacts(self, dry_run):
        """Phase 1: Link/Create contacts for all clients with jobs + test client"""
        # Validate test client exists - required for testing Xero flows
        cd = CompanyDefaults.get_solo()
        if not cd.test_client_name:
            raise ValueError(
                "CompanyDefaults.test_client_name is not set. "
                "This is required for Xero sync testing."
            )
        test_client = Client.objects.filter(name=cd.test_client_name).first()
        if not test_client:
            raise ValueError(
                f"Test client '{cd.test_client_name}' not found in database. "
                "Ensure the test client is created before running Xero sync."
            )

        # Find clients with jobs that need xero_contact_id
        client_ids_needing_sync = set(
            Client.objects.filter(
                jobs__isnull=False, xero_contact_id__isnull=True
            ).values_list("id", flat=True)
        )

        # Also include test client if it needs syncing
        if not test_client.xero_contact_id:
            client_ids_needing_sync.add(test_client.id)
            self.stdout.write(f"Including test client: {cd.test_client_name}")

        clients_needing_sync = Client.objects.filter(id__in=client_ids_needing_sync)

        self.stdout.write(
            f"Found {clients_needing_sync.count()} clients needing Xero contact IDs"
        )

        if not clients_needing_sync.exists():
            self.stdout.write("All clients with jobs already have Xero contact IDs")
            return 0

        if dry_run:
            for client in clients_needing_sync[:10]:  # Show first 10
                job_count = client.jobs.count()
                self.stdout.write(
                    f"  • Would process: {client.name} ({job_count} jobs)"
                )
            if clients_needing_sync.count() > 10:
                self.stdout.write(f"  ... and {clients_needing_sync.count() - 10} more")
            return clients_needing_sync.count()

        # Call sync module for bulk processing
        self.stdout.write("Processing clients with Xero sync module...")
        results = seed_clients_to_xero(clients_needing_sync)

        # Report results
        self.stdout.write(
            f"Contacts Summary: {results['linked']} linked, {results['created']} created"
        )

        if results["failed"]:
            self.stdout.write(f"Failed to process {len(results['failed'])} clients:")
            for name in results["failed"][:5]:  # Show first 5 failures
                self.stdout.write(f"  • {name}")
            if len(results["failed"]) > 5:
                self.stdout.write(f"  ... and {len(results['failed']) - 5} more")

        return results["linked"] + results["created"]

    def process_projects(self, dry_run):
        """Phase 2: Create projects for all jobs whose clients have xero_contact_id"""
        # Find jobs that need xero_project_id
        jobs_needing_sync = Job.objects.filter(
            client__xero_contact_id__isnull=False, xero_project_id__isnull=True
        )

        self.stdout.write(
            f"Found {jobs_needing_sync.count()} jobs needing Xero project IDs"
        )

        if not jobs_needing_sync.exists():
            self.stdout.write(
                "All jobs with valid clients already have Xero project IDs"
            )
            return 0

        if dry_run:
            for job in jobs_needing_sync[:10]:  # Show first 10
                self.stdout.write(
                    f"  • Would create project: {job.name} (Client: {job.client.name})"
                )
            if jobs_needing_sync.count() > 10:
                self.stdout.write(f"  ... and {jobs_needing_sync.count() - 10} more")
            return jobs_needing_sync.count()

        # Call sync module for bulk processing
        self.stdout.write("Processing jobs with Xero sync module...")
        results = seed_jobs_to_xero(jobs_needing_sync)

        # Report results
        self.stdout.write(f"Projects Summary: {results['created']} created")

        if results["failed"]:
            self.stdout.write(f"Failed to process {len(results['failed'])} jobs:")
            for name in results["failed"][:5]:  # Show first 5 failures
                self.stdout.write(f"  • {name}")
            if len(results["failed"]) > 5:
                self.stdout.write(f"  ... and {len(results['failed']) - 5} more")

        return results["created"]

    def process_invoices(self, dry_run):
        """Phase 3: Delete orphaned invoices, re-create job-linked invoices in dev Xero."""
        result = {"created": 0, "orphans_deleted": 0}

        # Delete invoices not linked to any job
        orphaned = Invoice.objects.filter(job__isnull=True)
        orphan_count = orphaned.count()
        self.stdout.write(f"Found {orphan_count} orphaned invoices (no job link)")

        if orphan_count > 0:
            if dry_run:
                for inv in orphaned[:5]:
                    self.stdout.write(
                        f"  • Would delete: {inv.number} ({inv.client.name})"
                    )
                if orphan_count > 5:
                    self.stdout.write(f"  ... and {orphan_count - 5} more")
            else:
                orphaned.delete()
                self.stdout.write(f"Deleted {orphan_count} orphaned invoices")
            result["orphans_deleted"] = orphan_count

        xero_api = AccountingApi(api_client)
        xero_tenant_id = get_tenant_id()

        # Find job-linked invoices not yet seeded to this Xero tenant
        job_invoices = (
            Invoice.objects.filter(job__isnull=False)
            .exclude(xero_tenant_id=xero_tenant_id)
            .select_related("job", "client")
        )
        already_seeded = Invoice.objects.filter(
            job__isnull=False, xero_tenant_id=xero_tenant_id
        ).count()
        self.stdout.write(
            f"Found {job_invoices.count()} invoices to seed "
            f"({already_seeded} already seeded, skipped)"
        )

        if not job_invoices.exists():
            return result

        if dry_run:
            for inv in job_invoices[:10]:
                self.stdout.write(
                    f"  • Would seed: {inv.number} - {inv.client.name} "
                    f"(${inv.total_excl_tax})"
                )
            if job_invoices.count() > 10:
                self.stdout.write(f"  ... and {job_invoices.count() - 10} more")
            return result

        # Skip invoices whose client has no xero_contact_id (contacts not seeded)
        skipped_no_contact = 0
        invoices_to_seed = []
        for inv in job_invoices:
            if not inv.client.xero_contact_id:
                skipped_no_contact += 1
                continue
            invoices_to_seed.append(inv)

        if skipped_no_contact > 0:
            self.stdout.write(
                f"Skipping {skipped_no_contact} invoices "
                f"(client missing xero_contact_id - run contacts first)"
            )

        # Fetch existing invoices from Xero to detect interrupted previous runs
        self.stdout.write("Fetching existing invoices from Xero...")
        existing_invoices = fetch_xero_entity_lookup(
            "invoices",
            key_func=lambda inv: inv.invoice_number,
            value_func=lambda inv: inv.invoice_id,
        )
        self.stdout.write(f"Found {len(existing_invoices)} existing invoices in Xero")

        linked = 0
        invoices_to_create = []
        for inv in invoices_to_seed:
            existing_id = existing_invoices.get(inv.number)
            if existing_id:
                inv.xero_id = existing_id
                inv.xero_tenant_id = xero_tenant_id
                inv.xero_last_synced = None
                inv.save(
                    update_fields=["xero_id", "xero_tenant_id", "xero_last_synced"]
                )
                linked += 1
                self.stdout.write(
                    f"  ↳ Linked existing: {inv.number} ({inv.client.name})"
                )
            else:
                invoices_to_create.append(inv)

        result["created"] = self._batch_create_invoices(
            invoices_to_create, xero_api, xero_tenant_id
        )

        self.stdout.write(
            f"Invoices Summary: {result['created']} created, "
            f"{linked} linked to existing, "
            f"{result['orphans_deleted']} orphans deleted"
        )
        return result

    def _build_invoice_payload(self, invoice):
        """Build a single Xero invoice payload dict from a local Invoice."""
        account_code = XeroAccount.objects.get(account_name="Sales").account_code

        contact = XeroContact(
            contact_id=invoice.client.xero_contact_id,
            name=invoice.client.name,
        )

        line_items = []
        for li in invoice.line_items.all():
            quantity = Decimal(str(li.quantity or 1))
            line_amount_excl_tax = (
                Decimal(str(li.line_amount_excl_tax))
                if li.line_amount_excl_tax is not None
                else None
            )
            unit_amount = self._get_invoice_line_unit_amount(
                quantity=quantity,
                line_amount_excl_tax=line_amount_excl_tax,
                unit_price=li.unit_price,
            )
            line_items.append(
                LineItem(
                    description=sanitize_for_xero(li.description),
                    quantity=float(quantity),
                    unit_amount=float(unit_amount),
                    line_amount=(
                        float(line_amount_excl_tax)
                        if line_amount_excl_tax is not None
                        else None
                    ),
                    tax_amount=float(li.tax_amount) if li.tax_amount else None,
                    account_code=account_code,
                )
            )

        if not line_items:
            description = f"Job: {invoice.job.job_number}"
            if invoice.job.description:
                description += f" - {sanitize_for_xero(invoice.job.description)}"
            line_items.append(
                LineItem(
                    description=description,
                    quantity=1,
                    unit_amount=float(invoice.total_excl_tax),
                    account_code=account_code,
                )
            )

        xero_invoice = XeroInvoice(
            type="ACCREC",
            contact=contact,
            line_items=line_items,
            date=format_date(invoice.date),
            due_date=format_date(invoice.due_date) if invoice.due_date else None,
            line_amount_types="Exclusive",
            currency_code="NZD",
            status="AUTHORISED",
            invoice_number=invoice.number,
        )

        if hasattr(invoice.job, "order_number") and invoice.job.order_number:
            xero_invoice.reference = invoice.job.order_number

        return convert_to_pascal_case(clean_payload(xero_invoice.to_dict()))

    def _batch_create_invoices(
        self, invoices_to_create, xero_api, xero_tenant_id, batch_size=50
    ):
        """Create invoices in Xero in batches; map response back by invoice_number."""
        if not invoices_to_create:
            return 0

        created = 0
        invoice_by_number = {inv.number: inv for inv in invoices_to_create}

        for i in range(0, len(invoices_to_create), batch_size):
            batch = invoices_to_create[i : i + batch_size]
            payloads = [self._build_invoice_payload(inv) for inv in batch]
            api_payload = {"Invoices": payloads}

            self.stdout.write(
                f"  • Sending batch of {len(payloads)} invoices "
                f"(batch {i // batch_size + 1})"
            )
            response, _, _ = xero_api.create_invoices(
                xero_tenant_id, invoices=api_payload, _return_http_data_only=False
            )

            if not response or not response.invoices:
                raise ValueError(
                    f"Empty response from Xero for invoice batch {i // batch_size + 1}"
                )

            time.sleep(1)

            for created_inv in response.invoices:
                local_inv = invoice_by_number.get(created_inv.invoice_number)
                if local_inv is None:
                    self.stdout.write(
                        f"  ! Could not map Xero invoice {created_inv.invoice_number} "
                        f"back to local record"
                    )
                    continue
                if not created_inv.invoice_id:
                    raise ValueError(
                        f"Xero response missing invoice_id for {local_inv.number}"
                    )
                local_inv.xero_id = created_inv.invoice_id
                local_inv.xero_tenant_id = xero_tenant_id
                local_inv.xero_last_synced = None
                local_inv.save(
                    update_fields=["xero_id", "xero_tenant_id", "xero_last_synced"]
                )
                created += 1
                self.stdout.write(
                    f"    ↳ Seeded: {local_inv.number} ({local_inv.client.name})"
                )

        return created

    @staticmethod
    def _get_invoice_line_unit_amount(quantity, line_amount_excl_tax, unit_price):
        """Return a unit amount consistent with Xero's Exclusive line totals."""
        if line_amount_excl_tax is not None and quantity != 0:
            return (line_amount_excl_tax / quantity).quantize(
                Decimal("0.0000"), rounding=ROUND_HALF_UP
            )

        if unit_price is not None:
            return Decimal(str(unit_price))

        return Decimal("0.0000")

    def process_quotes(self, dry_run):
        """Phase 3b: Delete orphaned quotes, re-create job-linked quotes in dev Xero."""
        result = {"created": 0, "orphans_deleted": 0}

        # Delete quotes not linked to any job (defensive — backup excludes these)
        orphaned = Quote.objects.filter(job__isnull=True)
        orphan_count = orphaned.count()
        self.stdout.write(f"Found {orphan_count} orphaned quotes (no job link)")

        if orphan_count > 0:
            if dry_run:
                for q in orphaned[:5]:
                    self.stdout.write(f"  - Would delete: {q.number} ({q.client.name})")
                if orphan_count > 5:
                    self.stdout.write(f"  ... and {orphan_count - 5} more")
            else:
                orphaned.delete()
                self.stdout.write(f"Deleted {orphan_count} orphaned quotes")
            result["orphans_deleted"] = orphan_count

        xero_api = AccountingApi(api_client)
        xero_tenant_id = get_tenant_id()

        # Find job-linked quotes not yet seeded to this Xero tenant
        job_quotes = (
            Quote.objects.filter(job__isnull=False)
            .exclude(xero_tenant_id=xero_tenant_id)
            .select_related("job", "client")
        )
        already_seeded = Quote.objects.filter(
            job__isnull=False, xero_tenant_id=xero_tenant_id
        ).count()
        self.stdout.write(
            f"Found {job_quotes.count()} quotes to seed "
            f"({already_seeded} already seeded, skipped)"
        )

        if not job_quotes.exists():
            return result

        if dry_run:
            for q in job_quotes[:10]:
                self.stdout.write(
                    f"  - Would seed: {q.number} - {q.client.name} "
                    f"(${q.total_excl_tax})"
                )
            if job_quotes.count() > 10:
                self.stdout.write(f"  ... and {job_quotes.count() - 10} more")
            return result

        # Skip quotes whose client has no xero_contact_id (contacts not seeded)
        skipped_no_contact = 0
        quotes_to_seed = []
        for q in job_quotes:
            if not q.client.xero_contact_id:
                skipped_no_contact += 1
                continue
            quotes_to_seed.append(q)

        # Fetch existing quotes from Xero to detect interrupted previous runs
        self.stdout.write("Fetching existing quotes from Xero...")
        existing_quotes = fetch_xero_entity_lookup(
            "quotes",
            key_func=lambda q: q.quote_number,
            value_func=lambda q: q.quote_id,
        )
        self.stdout.write(f"Found {len(existing_quotes)} existing quotes in Xero")

        linked = 0
        quotes_to_create = []
        for q in quotes_to_seed:
            existing_id = existing_quotes.get(q.number)
            if existing_id:
                q.xero_id = existing_id
                q.xero_tenant_id = xero_tenant_id
                q.save(update_fields=["xero_id", "xero_tenant_id"])
                linked += 1
                self.stdout.write(f"  ↳ Linked existing: {q.number} ({q.client.name})")
            else:
                quotes_to_create.append(q)

        result["created"] = self._batch_create_quotes(
            quotes_to_create, xero_api, xero_tenant_id
        )

        self.stdout.write(
            f"Quotes Summary: {result['created']} created, "
            f"{linked} linked to existing, "
            f"{result['orphans_deleted']} orphans deleted"
        )
        return result

    def _build_quote_payload(self, quote):
        """Build a single Xero quote payload dict from a local Quote."""
        account_code = XeroAccount.objects.get(account_name="Sales").account_code

        contact = XeroContact(
            contact_id=quote.client.xero_contact_id,
            name=quote.client.name,
        )

        description = f"Job: {quote.job.job_number}"
        if quote.job.description:
            description += f" - {sanitize_for_xero(quote.job.description)}"

        line_items = [
            LineItem(
                description=description,
                quantity=1,
                unit_amount=float(quote.total_excl_tax),
                account_code=account_code,
            )
        ]

        xero_quote = XeroQuote(
            contact=contact,
            line_items=line_items,
            date=format_date(quote.date),
            line_amount_types="Exclusive",
            currency_code="NZD",
            status="DRAFT",
            quote_number=quote.number,
        )

        if hasattr(quote.job, "order_number") and quote.job.order_number:
            xero_quote.reference = quote.job.order_number

        return convert_to_pascal_case(clean_payload(xero_quote.to_dict()))

    def _batch_create_quotes(
        self, quotes_to_create, xero_api, xero_tenant_id, batch_size=50
    ):
        """Create quotes in Xero in batches; map response back by quote_number."""
        if not quotes_to_create:
            return 0

        created = 0
        quote_by_number = {q.number: q for q in quotes_to_create}

        for i in range(0, len(quotes_to_create), batch_size):
            batch = quotes_to_create[i : i + batch_size]
            payloads = [self._build_quote_payload(q) for q in batch]
            api_payload = {"Quotes": payloads}

            self.stdout.write(
                f"  - Sending batch of {len(payloads)} quotes "
                f"(batch {i // batch_size + 1})"
            )
            response, _, _ = xero_api.create_quotes(
                xero_tenant_id, quotes=api_payload, _return_http_data_only=False
            )

            if not response or not response.quotes:
                raise ValueError(
                    f"Empty response from Xero for quote batch {i // batch_size + 1}"
                )

            time.sleep(1)

            for created_q in response.quotes:
                local_q = quote_by_number.get(created_q.quote_number)
                if local_q is None:
                    self.stdout.write(
                        f"  ! Could not map Xero quote {created_q.quote_number} "
                        f"back to local record"
                    )
                    continue
                if not created_q.quote_id:
                    raise ValueError(
                        f"Xero response missing quote_id for {local_q.number}"
                    )
                local_q.xero_id = created_q.quote_id
                local_q.xero_tenant_id = xero_tenant_id
                local_q.save(update_fields=["xero_id", "xero_tenant_id"])
                created += 1
                self.stdout.write(
                    f"    ↳ Seeded: {local_q.number} ({local_q.client.name})"
                )

        return created

    def process_stock_items(self, dry_run):
        """Phase 4: Sync stock items to Xero inventory."""
        # Find stock items that need xero_id
        stock_needing_sync = Stock.objects.filter(
            xero_id__isnull=True, is_active=True
        ).order_by("date")

        self.stdout.write(
            f"Found {stock_needing_sync.count()} stock items needing Xero sync"
        )

        if not stock_needing_sync.exists():
            self.stdout.write("All active stock items already have Xero IDs")
            return 0

        if dry_run:
            for stock in stock_needing_sync[:10]:  # Show first 10
                self.stdout.write(
                    f"  • Would sync: {stock.description} (qty: {stock.quantity}, cost: ${stock.unit_cost})"
                )
            if stock_needing_sync.count() > 10:
                self.stdout.write(f"  ... and {stock_needing_sync.count() - 10} more")
            return stock_needing_sync.count()

        # Call stock sync module for processing
        self.stdout.write("Syncing stock items to Xero...")
        results = sync_all_local_stock_to_xero(limit=None)

        # Report results
        self.stdout.write(
            f"Stock Summary: {results['synced_count']} synced, {results['failed_count']} failed"
        )

        if results["failed_items"]:
            self.stdout.write(
                f"Failed to sync {len(results['failed_items'])} stock items:"
            )
            for item in results["failed_items"][:5]:  # Show first 5 failures
                self.stdout.write(f"  • {item['description']} - {item['reason']}")
            if len(results["failed_items"]) > 5:
                self.stdout.write(f"  ... and {len(results['failed_items']) - 5} more")

        return results["synced_count"]

    def process_employees(self, dry_run):
        """Phase 5: Link/create payroll employees for all staff.

        Processes ALL staff who HAD xero_user_id in the backup (were linked in prod),
        including those who have left. This is important because:
        1. Historical timesheets may need to be posted for departed staff
        2. Xero should have the complete employee history with end_date set

        The backup's xero_user_id values are for PROD's Xero tenant, so we:
        1. Identify staff who had xero_user_id (were linked in prod)
        2. Clear those IDs (wrong tenant)
        3. Re-link to DEV's Xero using job_title UUID, email, or name matching
        4. Create in DEV's Xero if no match found (with end_date for departed staff)

        Staff without xero_user_id in backup are left alone (weren't linked in prod).
        """
        # Find ALL staff WITH xero_user_id set (from backup = were linked in prod)
        # Include staff who have left - they need valid Xero IDs for historical timesheets
        staff_to_sync = list(Staff.objects.filter(xero_user_id__isnull=False))

        # Staff without xero_user_id were not linked in prod - leave them alone
        unlinked_count = Staff.objects.filter(xero_user_id__isnull=True).count()

        self.stdout.write(
            f"Found {len(staff_to_sync)} staff to sync (had xero_user_id in backup)"
        )
        self.stdout.write(
            f"Skipping {unlinked_count} staff (no xero_user_id in backup)"
        )

        if not staff_to_sync:
            self.stdout.write("No staff need Xero employee sync")
            return {"linked": 0, "created": 0, "already_linked": 0}

        if dry_run:
            for staff in staff_to_sync[:10]:  # Show first 10
                self.stdout.write(
                    f"  • Would process: {staff.first_name} {staff.last_name} ({staff.email})"
                )
            if len(staff_to_sync) > 10:
                self.stdout.write(f"  ... and {len(staff_to_sync) - 10} more")
            return {
                "linked": 0,
                "created": 0,
                "already_linked": 0,
                "would_process": len(staff_to_sync),
            }

        # Clear prod xero_user_id in memory only (not DB) so sync_staff
        # will process them. DB keeps prod IDs as crash recovery — if the
        # process dies mid-way, re-running will still find unprocessed staff.
        # sync_staff's _link_staff() saves the new dev ID to DB on success.
        self.stdout.write(
            f"Clearing {len(staff_to_sync)} prod xero_user_id values in memory before re-linking..."
        )
        for staff in staff_to_sync:
            staff.xero_user_id = None

        # Use PayrollEmployeeSyncService to link (by job_title UUID, email, or name)
        # and create missing employees in dev's Xero
        self.stdout.write("Syncing staff with Xero Payroll...")
        summary = PayrollEmployeeSyncService.sync_staff(
            staff_queryset=staff_to_sync,
            dry_run=False,
            allow_create=True,  # Create if not found in dev's Xero
        )

        # Report results
        linked_count = len(summary.get("linked", []))
        created_count = len(summary.get("created", []))
        missing_count = len(summary.get("missing", []))

        self.stdout.write(
            f"Employee Summary: {linked_count} linked, {created_count} created"
        )

        if summary.get("linked"):
            self.stdout.write("Linked by matching:")
            for link in summary["linked"][:5]:
                self.stdout.write(
                    f"  • {link['first_name']} {link['last_name']} → {link['xero_employee_id']}"
                )
            if len(summary["linked"]) > 5:
                self.stdout.write(f"  ... and {len(summary['linked']) - 5} more")

        if summary.get("created"):
            self.stdout.write("Created in Xero:")
            for created in summary["created"][:5]:
                self.stdout.write(
                    f"  • {created['first_name']} {created['last_name']} → {created['xero_employee_id']}"
                )
            if len(summary["created"]) > 5:
                self.stdout.write(f"  ... and {len(summary['created']) - 5} more")

        if missing_count > 0:
            self.stdout.write(f"Failed to process {missing_count} staff members")
            for missing in summary["missing"][:5]:
                self.stdout.write(
                    f"  • {missing['first_name']} {missing['last_name']} ({missing['email']})"
                )

        return {
            "linked": linked_count,
            "created": created_count,
            "already_linked": 0,  # We cleared and re-linked, so none are "already linked"
        }

    def clear_production_xero_ids(self, dry_run):
        """Clear production Xero IDs from all relevant tables."""
        # Safety check - never run on production server
        hostname = socket.gethostname().lower()
        db_name = settings.DATABASES["default"]["NAME"]

        if "msm" in hostname or "prod" in hostname:
            self.stdout.write(
                self.style.ERROR(
                    f"ERROR: Refusing to run on production server: {hostname}"
                )
            )
            self.stdout.write(
                "This operation is only for development environments after production restore."
            )
            return

        self.stdout.write(f"Host: {hostname}")
        self.stdout.write(f"Database: {db_name}")
        self.stdout.write("This will clear Xero IDs from restored production data.")
        self.stdout.write("Records will be re-linked during the sync process.")

        if dry_run:
            self.stdout.write("Dry run - would clear Xero IDs but not making changes")
            return

        tables_cleared = []

        with connection.cursor() as cursor:
            # Clear client contact IDs - allows re-linking by name
            self.stdout.write("Clearing client xero_contact_id values...")
            if self._table_exists(cursor, "client_client"):
                cursor.execute(
                    "UPDATE client_client SET xero_contact_id = NULL WHERE xero_contact_id IS NOT NULL"
                )
                client_count = cursor.rowcount
                if client_count > 0:
                    tables_cleared.append(f"client_client: {client_count} records")
            else:
                self.stdout.write("  WARNING: client_client table not found - skipping")

            # Clear job project IDs - allows fresh project sync
            self.stdout.write("Clearing job xero_project_id values...")
            if self._table_exists(cursor, "job_job") and self._column_exists(
                cursor, "job_job", "xero_project_id"
            ):
                cursor.execute(
                    "UPDATE job_job SET xero_project_id = NULL WHERE xero_project_id IS NOT NULL"
                )
                job_count = cursor.rowcount
                if job_count > 0:
                    tables_cleared.append(f"job_job: {job_count} records")
            else:
                self.stdout.write(
                    "  WARNING: job_job.xero_project_id column not found - skipping"
                )

            # Invoice/Quote xero_ids are NOT NULL so can't be cleared here.
            # process_invoices()/process_quotes() handle them: orphans are
            # deleted, job-linked records are re-created in dev Xero with new xero_ids.
            self.stdout.write(
                "Invoices: handled by process_invoices (orphans deleted, "
                "job-linked re-created with dev xero_id)"
            )
            self.stdout.write(
                "Quotes: handled by process_quotes (orphans deleted, "
                "job-linked re-created with dev xero_id)"
            )

            # Clear purchase order IDs
            self.stdout.write("Clearing purchase order xero_id values...")
            if self._table_exists(
                cursor, "purchasing_purchaseorder"
            ) and self._column_exists(cursor, "purchasing_purchaseorder", "xero_id"):
                cursor.execute(
                    "UPDATE purchasing_purchaseorder SET xero_id = NULL WHERE xero_id IS NOT NULL"
                )
                po_count = cursor.rowcount
                if po_count > 0:
                    tables_cleared.append(
                        f"purchasing_purchaseorder: {po_count} records"
                    )

            # Clear stock item IDs - allows re-creation in UAT Xero tenant
            self.stdout.write("Clearing stock xero_id values...")
            if self._table_exists(cursor, "purchasing_stock") and self._column_exists(
                cursor, "purchasing_stock", "xero_id"
            ):
                cursor.execute(
                    "UPDATE purchasing_stock SET xero_id = NULL WHERE xero_id IS NOT NULL"
                )
                stock_count = cursor.rowcount
                if stock_count > 0:
                    tables_cleared.append(f"purchasing_stock: {stock_count} records")

            # Clear XeroPayItem xero_id and xero_tenant_id — these are
            # environment-specific and get set when connecting to the target Xero
            self.stdout.write(
                "Clearing XeroPayItem xero_id and xero_tenant_id values..."
            )
            if self._table_exists(cursor, "workflow_xeropayitem"):
                cursor.execute(
                    "UPDATE workflow_xeropayitem SET xero_id = NULL, xero_tenant_id = NULL "
                    "WHERE xero_id IS NOT NULL"
                )
                pi_count = cursor.rowcount
                if pi_count > 0:
                    tables_cleared.append(f"workflow_xeropayitem: {pi_count} records")

            # NOTE: Do NOT clear staff xero_user_id here.
            # We preserve it from the backup to know which staff were linked in prod.
            # Phase 5 uses this to decide which staff to create/link in Xero.
            self.stdout.write("Preserving staff xero_user_id values (used by Phase 5)")

        # Summary
        if tables_cleared:
            self.stdout.write("Cleared Xero IDs from:")
            for table_info in tables_cleared:
                self.stdout.write(f"  • {table_info}")
        else:
            self.stdout.write("No Xero IDs found to clear")

    def _table_exists(self, cursor, table_name):
        """Check if a table exists in the database."""
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM information_schema.tables
            WHERE table_schema = %s AND table_name = %s
        """,
            ["public", table_name],
        )
        return cursor.fetchone()[0] > 0

    def _column_exists(self, cursor, table_name, column_name):
        """Check if a column exists in a table."""
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s AND column_name = %s
        """,
            ["public", table_name, column_name],
        )
        return cursor.fetchone()[0] > 0
