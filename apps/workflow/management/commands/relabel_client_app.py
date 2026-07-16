"""Relabel the historical `client` app to `company` (KAN-278 one-time surgery).

Runs before `migrate` (deploy.sh calls it for every instance). Idempotent:
keys off django_migrations rows still recorded under the old label.

TEMPORARY KAN-278: remove this command and its deploy hook after every
production instance has completed the cutover and produced a verified
company-schema backup.

The historic pre-squash rows (0001_initial .. 0023_drop_scalar_phone_fields)
are DELETED rather than relabelled: with the squash's `replaces` lists gone,
a blanket relabel would strand ("company", "0001_initial")-style ghost rows
that collide with any future company migration reusing one of those names
and can never be pruned. Only the baseline row carries state worth keeping.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

TABLE_RENAMES = [
    ("client_client", "company_client"),
    ("client_clientcontact", "company_clientcontact"),
    ("client_clientcontactmethod", "company_clientcontactmethod"),
    ("client_suppliersearchalias", "company_suppliersearchalias"),
    ("client_supplierpickupaddress", "company_supplierpickupaddress"),
]


class Command(BaseCommand):
    help = (
        "Relabel the 'client' app to 'company' in django_migrations/"
        "content types/tables."
    )

    def handle(
        self,
        *args: object,  # object: Django's untyped pass-through args; unused here
        **options: object,  # object: Django's untyped pass-through args; unused here
    ) -> None:
        # Atomic so a crash mid-surgery rolls back everything. The idempotence
        # guard keys off django_migrations, so a half-applied state (UPDATE done,
        # ALTERs not) must be impossible; Postgres DDL is transactional.
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM django_migrations WHERE app = 'client'"
            )
            row = cursor.fetchone()
            if row is None:
                raise RuntimeError("django_migrations COUNT(*) query returned no row")
            (stale_rows,) = row
            if stale_rows == 0:
                self.stdout.write("Already relabelled; nothing to do.")
                return
            cursor.execute(
                "SELECT COUNT(*) FROM django_migrations "
                "WHERE app = 'client' AND name = '0001_baseline'"
            )
            baseline_row = cursor.fetchone()
            if baseline_row is None:
                raise RuntimeError("django_migrations COUNT(*) query returned no row")
            (baseline_count,) = baseline_row
            if baseline_count == 0:
                raise CommandError(
                    "django_migrations has app='client' rows but no "
                    "('client', '0001_baseline') row - this database predates "
                    "the migration squash. Deploy a pre-squash release, run "
                    "migrate, then retry this deploy."
                )
            cursor.execute(
                "DELETE FROM django_migrations "
                "WHERE app = 'client' AND name <> '0001_baseline'"
            )
            cursor.execute(
                "UPDATE django_migrations SET app = 'company' WHERE app = 'client'"
            )
            cursor.execute(
                "UPDATE django_content_type SET app_label = 'company' "
                "WHERE app_label = 'client'"
            )
            renamed_tables = 0
            for old, new in TABLE_RENAMES:
                cursor.execute("SELECT to_regclass(%s)", [old])
                if cursor.fetchone()[0] is None:
                    continue
                cursor.execute(f'ALTER TABLE "{old}" RENAME TO "{new}"')
                renamed_tables += 1
        self.stdout.write(
            self.style.SUCCESS(
                f"Relabelled the client app: dropped {stale_rows - 1} historic "
                "ledger rows, kept 0001_baseline, renamed content types and "
                f"{renamed_tables} tables."
            )
        )
