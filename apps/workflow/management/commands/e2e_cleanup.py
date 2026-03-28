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

from apps.accounting.models import Invoice
from apps.client.models import Client, ClientContact
from apps.job.models import Job
from apps.purchasing.models import PurchaseOrder

logger = logging.getLogger(__name__)

TEST_DATA_PREFIX = "[TEST]"
TEST_CLIENT_NAME = "ABC Carpet Cleaning TEST IGNORE"
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
        test_contacts = ClientContact.objects.filter(name__startswith=TEST_DATA_PREFIX)
        test_clients = Client.objects.filter(name__startswith=TEST_DATA_PREFIX)

        # Legacy E2E-prefixed clients and their data
        from django.db.models import Q

        legacy_q = Q()
        for prefix in LEGACY_E2E_PREFIXES:
            legacy_q |= Q(name__startswith=prefix)
        legacy_clients = Client.objects.filter(legacy_q)
        legacy_client_jobs = Job.objects.filter(client__in=legacy_clients)
        legacy_client_contacts = ClientContact.objects.filter(client__in=legacy_clients)

        # Test client data (all jobs/contacts on the test client are test artifacts)
        test_client_qs = Client.objects.filter(name=TEST_CLIENT_NAME)
        test_client_jobs = Job.objects.filter(client__in=test_client_qs)
        test_client_contacts = ClientContact.objects.filter(client__in=test_client_qs)

        # Report
        self.stdout.write("\n=== E2E Test Data ===\n")

        self._report_queryset("[TEST]-prefixed jobs", test_jobs, "name")
        self._report_queryset("[TEST]-prefixed contacts", test_contacts, "name")
        self._report_queryset("[TEST]-prefixed clients", test_clients, "name")
        self._report_queryset("Legacy E2E clients", legacy_clients, "name")
        self._report_queryset("Legacy E2E client jobs", legacy_client_jobs, "name")
        self._report_queryset(
            "Legacy E2E client contacts", legacy_client_contacts, "name"
        )
        self._report_queryset(
            f"Jobs on test client ({TEST_CLIENT_NAME})", test_client_jobs, "name"
        )
        self._report_queryset(
            f"Contacts on test client ({TEST_CLIENT_NAME})",
            test_client_contacts,
            "name",
        )

        total = (
            test_jobs.count()
            + test_contacts.count()
            + test_clients.count()
            + legacy_clients.count()
            + legacy_client_jobs.count()
            + legacy_client_contacts.count()
            + test_client_jobs.count()
            + test_client_contacts.count()
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
        # setval is non-transactional in PostgreSQL, but we need to commit any
        # pending transaction state before proceeding.
        self.stdout.write("\nSyncing sequences...")
        from django.db import connection

        # Ensure we're not inside a transaction that could interfere
        connection.ensure_connection()
        with connection.cursor() as cursor:
            if connection.in_atomic_block:
                # Force commit so setval takes effect
                pass  # setval is already non-transactional in PG
            cursor.execute("""
                DO $$
                DECLARE
                    r RECORD;
                BEGIN
                    FOR r IN
                        SELECT
                            quote_ident(n.nspname) || '.' || quote_ident(c.relname) AS seq_name,
                            quote_ident(tn.nspname) || '.' || quote_ident(t.relname) AS table_name,
                            quote_ident(a.attname) AS column_name
                        FROM pg_class c
                        JOIN pg_namespace n ON n.oid = c.relnamespace
                        JOIN pg_depend d ON d.objid = c.oid AND d.deptype = 'a'
                        JOIN pg_class t ON t.oid = d.refobjid
                        JOIN pg_namespace tn ON tn.oid = t.relnamespace
                        JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = d.refobjsubid
                        WHERE c.relkind = 'S'
                    LOOP
                        EXECUTE format(
                            'SELECT setval(%L, COALESCE((SELECT MAX(%s) FROM %s), 1))',
                            r.seq_name, r.column_name, r.table_name
                        );
                    END LOOP;
                END $$;
            """)
        # Verify the fix took effect
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT last_value FROM workflow_historicaljob_history_id_seq"
            )
            seq_val = cursor.fetchone()[0]
            cursor.execute("SELECT MAX(history_id) FROM workflow_historicaljob")
            max_val = cursor.fetchone()[0] or 0
            self.stdout.write(
                f"  historicaljob sequence: {seq_val} (max in table: {max_val})"
            )
            if seq_val < max_val:
                # Direct setval as a fallback
                cursor.execute(
                    "SELECT setval('workflow_historicaljob_history_id_seq', %s)",
                    [max_val],
                )
                self.stdout.write(f"  Fixed: set to {max_val}")
        self.stdout.write("Sequences synced.")

        # Collect all jobs that will be deleted (union of all sources)
        all_jobs_to_delete = (
            test_jobs | test_client_jobs | legacy_client_jobs
        ).distinct()

        # Check for invoices linked to these jobs (PROTECTED FK)
        linked_invoices = Invoice.objects.filter(job__in=all_jobs_to_delete)
        if linked_invoices.exists():
            self._report_queryset(
                "Invoices linked to test jobs (will be deleted)",
                linked_invoices,
                "number",
            )

        # Collect all clients to delete
        all_clients_to_delete = (test_clients | legacy_clients).distinct()

        # Find POs referencing these clients (PROTECTED FK on supplier)
        linked_pos = PurchaseOrder.objects.filter(supplier__in=all_clients_to_delete)

        if linked_pos.exists():
            self._report_queryset(
                "Purchase orders linked to test clients (will be deleted)",
                linked_pos,
                "id",
            )

        # Delete in correct order — PROTECTED FKs first, then cascading
        self.stdout.write("\nDeleting...")

        # 1. Invoices on test jobs (PROTECTED FK)
        count, details = linked_invoices.delete()
        if count:
            self.stdout.write(f"  Invoices: {count} objects ({details})")

        # 2. POs on test clients (PROTECTED FK on supplier)
        count, details = linked_pos.delete()
        if count:
            self.stdout.write(f"  Purchase orders: {count} objects ({details})")

        # 3. Jobs on test client (cascade deletes cost sets, cost lines, etc.)
        count, details = test_client_jobs.delete()
        self.stdout.write(f"  Test client jobs: {count} objects ({details})")

        # 4. Contacts on test client
        count, details = test_client_contacts.delete()
        self.stdout.write(f"  Test client contacts: {count} objects ({details})")

        # 5. Legacy client data
        count, details = legacy_client_jobs.delete()
        self.stdout.write(f"  Legacy client jobs: {count} objects ({details})")

        count, details = legacy_client_contacts.delete()
        self.stdout.write(f"  Legacy client contacts: {count} objects ({details})")

        count, details = legacy_clients.delete()
        self.stdout.write(f"  Legacy clients: {count} objects ({details})")

        # 6. [TEST]-prefixed items (may overlap with above, that's fine)
        count, details = test_jobs.delete()
        self.stdout.write(f"  [TEST] jobs: {count} objects ({details})")

        count, details = test_contacts.delete()
        self.stdout.write(f"  [TEST] contacts: {count} objects ({details})")

        count, details = test_clients.delete()
        self.stdout.write(f"  [TEST] clients: {count} objects ({details})")

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
