"""Write the ``<dump>.migrations.json`` sidecar for an existing dump.

The nightly ``scripts/backup_db.sh`` calls this after ``pg_dump`` so every
backup carries the same restore-consumed schema snapshot the scrubbed
pipeline writes (one sidecar convention; see
``apps/diagnostics/services/migrations_snapshot.py``).
"""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import DEFAULT_DB_ALIAS

from apps.diagnostics.services.migrations_snapshot import (
    EmptyMigrationLedgerError,
    write_migrations_snapshot,
)


class Command(BaseCommand):
    """Snapshot django_migrations beside a dump file."""

    help = "Writes <dump>.migrations.json describing this database's migration state."

    def add_arguments(self, parser: CommandParser) -> None:
        """Require the dump the sidecar describes."""
        parser.add_argument(
            "--dump",
            required=True,
            help="Path of the dump file the sidecar sits beside (must exist).",
        )

    def handle(self, *_args: object, **options: object) -> None:
        """Refuse a missing dump, then write the sidecar."""
        dump_path = Path(str(options["dump"]))
        if not dump_path.is_file():
            raise CommandError(f"dump file does not exist: {dump_path}")
        try:
            snapshot_path = write_migrations_snapshot(DEFAULT_DB_ALIAS, dump_path)
        except EmptyMigrationLedgerError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(f"migrations snapshot written: {snapshot_path}")
