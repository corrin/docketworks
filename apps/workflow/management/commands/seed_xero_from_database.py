import logging
import socket

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection
from dotenv import load_dotenv

from apps.accounts.models import Staff
from apps.client.models import Client
from apps.job.models import Job
from apps.purchasing.models import Stock
from apps.timesheet.services.payroll_employee_sync import PayrollEmployeeSyncService
from apps.workflow.api.xero.stock_sync import sync_all_local_stock_to_xero
from apps.workflow.api.xero.sync import seed_clients_to_xero, seed_jobs_to_xero
from apps.workflow.models import CompanyDefaults

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
            help="Sync specific entities only. Comma-separated: pay_items,contacts,projects,stock,employees",
        )
        parser.add_argument(
            "--skip-clear",
            action="store_true",
            help="Skip clearing production Xero IDs (useful for re-running after partial failure)",
        )

    VALID_ENTITIES = {"contacts", "projects", "stock", "employees"}

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        only_arg = options.get("only")
        skip_clear = options.get("skip_clear", False)

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

        contacts_processed = 0
        projects_processed = 0
        stock_processed = 0
        employees_result = {"linked": 0, "created": 0, "already_linked": 0}

        # Clear production Xero IDs (unless skipped)
        if not skip_clear:
            self.stdout.write("Clearing Production Xero IDs...")
            self.clear_production_xero_ids(dry_run)

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

        # Sync stock items
        if "stock" in entities_to_sync:
            self.stdout.write("Syncing Stock Items...")
            stock_processed = self.process_stock_items(dry_run)

        # Sync payroll employees
        if "employees" in entities_to_sync:
            self.stdout.write("Syncing Payroll Employees...")
            employees_result = self.process_employees(dry_run)

        # Summary
        self.stdout.write("COMPLETED")
        self.stdout.write(f"Contacts processed: {contacts_processed}")
        self.stdout.write(f"Projects processed: {projects_processed}")
        self.stdout.write(f"Stock items processed: {stock_processed}")
        self.stdout.write(
            f"Employees linked: {employees_result['linked']}, "
            f"created: {employees_result['created']}, "
            f"already linked: {employees_result['already_linked']}"
        )

        if dry_run:
            self.stdout.write("Dry run complete - no changes made")
        else:
            # Enable Xero sync now that prod IDs are cleared and dev IDs are seeded
            company = CompanyDefaults.get_solo()
            company.enable_xero_sync = True
            company.save()
            self.stdout.write("Xero seeding complete! enable_xero_sync is now True.")

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

    def process_stock_items(self, dry_run):
        """Phase 3: Sync stock items to Xero inventory."""
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
        """Phase 4: Link/create payroll employees for all staff.

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

            # TODO: Seed invoices/bills/quotes/credit notes to dev Xero
            # and overwrite xero_id. For now, leave stale production xero_ids
            # in place — they're harmless (xero_id is NOT NULL so can't clear).

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
            # Phase 4 uses this to decide which staff to create/link in Xero.
            self.stdout.write("Preserving staff xero_user_id values (used by Phase 4)")

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
