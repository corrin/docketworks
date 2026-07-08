"""Tests for the KAN-278 relabel_client_app one-time DB surgery.

The fully-migrated test DB is post-rename (tables are ``company_company``
etc., ledger rows say app='company'), so each test stages the legacy state
it needs with raw DDL/DML and restores the live table names afterwards -
the surgery's net DDL is deliberately NOT zero (it only does the app-label
half of the table renames; the rename migration does the model half).
"""

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import TransactionTestCase

# The pre-squash client migration names every production ledger carried
# (verified against the dev ledger, which mirrored prod at the squash).
HISTORIC_CLIENT_MIGRATIONS = [
    "0001_initial",
    "0002_clientcontact",
    "0003_add_xero_merge_tracking",
    "0004_populate_merge_fields",
    "0005_client_is_supplier",
    "0006_alter_client_name",
    "0007_delete_empty_name_contacts",
    "0008_merge_duplicate_contacts",
    "0009_clientcontact_unique_client_contact_name",
    "0010_add_is_active_to_clientcontact",
    "0011_convert_empty_strings_to_null",
    "0012_supplierpickupaddress",
    "0013_add_google_fields_to_pickup_address",
    "0014_add_suburb_to_pickup_address",
    "0015_populate_xero_addresses",
    "0016_alter_client_table_alter_clientcontact_table_and_more",
    "0017_reassign_stranded_merged_client_fks",
    "0018_client_allow_jobs",
    "0019_client_name_fts_index",
    "0020_suppliersearchalias_and_more",
    "0021_clientcontactmethod",
    "0022_client_name_trgm_index",
    "0023_drop_scalar_phone_fields",
]

# live table name -> pre-surgery (legacy) table name
LEGACY_TABLE_NAMES = [
    ("company_company", "client_client"),
    ("company_clientcontact", "client_clientcontact"),
    ("company_clientcontactmethod", "client_clientcontactmethod"),
    ("company_suppliersearchalias", "client_suppliersearchalias"),
    ("company_supplierpickupaddress", "client_supplierpickupaddress"),
]


def _insert_ghost_rows(cursor) -> None:
    for name in HISTORIC_CLIENT_MIGRATIONS:
        cursor.execute(
            "INSERT INTO django_migrations (app, name, applied) "
            "VALUES ('client', %s, NOW())",
            [name],
        )


class RelabelClientAppTests(TransactionTestCase):
    def test_noop_on_fresh_db(self) -> None:
        # The migrated test DB has no app='client' rows: the command must
        # no-op without touching tables.
        call_command("relabel_client_app")
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM django_migrations WHERE app = 'client'"
            )
            self.assertEqual(cursor.fetchone()[0], 0)
            cursor.execute("SELECT to_regclass('company_company')")
            self.assertIsNotNone(cursor.fetchone()[0])

    def test_relabels_postsquash_ledger(self) -> None:
        # Stage the real pre-deploy state: legacy table names, the baseline
        # ledger row under app='client', 23 historic ghost rows, content
        # types under app_label='client'.
        with connection.cursor() as cursor:
            for live, legacy in LEGACY_TABLE_NAMES:
                cursor.execute(f'ALTER TABLE "{live}" RENAME TO "{legacy}"')
            cursor.execute(
                "UPDATE django_migrations SET app = 'client' "
                "WHERE app = 'company' AND name = '0001_baseline'"
            )
            _insert_ghost_rows(cursor)
            cursor.execute(
                "UPDATE django_content_type SET app_label = 'client' "
                "WHERE app_label = 'company'"
            )

        try:
            call_command("relabel_client_app")
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT COUNT(*) FROM django_migrations WHERE app = 'client'"
                )
                self.assertEqual(cursor.fetchone()[0], 0)
                cursor.execute(
                    "SELECT COUNT(*) FROM django_migrations "
                    "WHERE app = 'company' AND name = '0001_baseline'"
                )
                self.assertEqual(cursor.fetchone()[0], 1)
                # The historic ghosts are deleted, not relabelled.
                cursor.execute(
                    "SELECT COUNT(*) FROM django_migrations "
                    "WHERE app = 'company' AND name = ANY(%s)",
                    [HISTORIC_CLIENT_MIGRATIONS],
                )
                self.assertEqual(cursor.fetchone()[0], 0)
                cursor.execute(
                    "SELECT COUNT(*) FROM django_content_type "
                    "WHERE app_label = 'client'"
                )
                self.assertEqual(cursor.fetchone()[0], 0)
                cursor.execute(
                    "SELECT COUNT(*) FROM django_content_type "
                    "WHERE app_label = 'company'"
                )
                self.assertGreater(cursor.fetchone()[0], 0)
                # Surgery does the label half only: client_client ends up at
                # company_client; the rename migration owns the model half.
                cursor.execute("SELECT to_regclass('company_client')")
                self.assertIsNotNone(cursor.fetchone()[0])
                cursor.execute("SELECT to_regclass('client_client')")
                self.assertIsNone(cursor.fetchone()[0])

            # Second run must be a clean no-op.
            call_command("relabel_client_app")
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT COUNT(*) FROM django_migrations WHERE app = 'client'"
                )
                self.assertEqual(cursor.fetchone()[0], 0)
        finally:
            # Restore the live schema for subsequent tests: only the main
            # table sits at its label-half name (company_client).
            with connection.cursor() as cursor:
                cursor.execute("SELECT to_regclass('company_client')")
                if cursor.fetchone()[0] is not None:
                    cursor.execute(
                        "ALTER TABLE company_client RENAME TO company_company"
                    )

    def test_aborts_on_presquash_ledger(self) -> None:
        # app='client' rows without a ('client', '0001_baseline') row mean a
        # pre-squash database: the command must abort loudly and leave every
        # staged row in place (its transaction rolls back atomically).
        with connection.cursor() as cursor:
            _insert_ghost_rows(cursor)
        try:
            with self.assertRaises(CommandError):
                call_command("relabel_client_app")
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT COUNT(*) FROM django_migrations WHERE app = 'client'"
                )
                self.assertEqual(cursor.fetchone()[0], len(HISTORIC_CLIENT_MIGRATIONS))
                cursor.execute("SELECT to_regclass('company_company')")
                self.assertIsNotNone(cursor.fetchone()[0])
        finally:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM django_migrations WHERE app = 'client'")
