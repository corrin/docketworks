"""Audit the posted inventory ledger in one read-only snapshot."""

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from apps.purchasing.services.stock_movement_service import inventory_audit_findings


class Command(BaseCommand):
    """Expose recurring inventory reconciliation to deployment operators."""

    help = "Audit inventory openings, balances, costs, reversals and net receipts without writes."

    def handle(self, *_args: object, **_options: object) -> None:
        """Report ledger discrepancies without repairs."""
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            findings = inventory_audit_findings()
            for label, rows in findings.items():
                self.stdout.write(f"{label}: {len(rows)} discrepancies")
                for row in rows:
                    self.stdout.write(f"  {row}")
            if findings:
                raise CommandError("Inventory audit failed; no data changed.")
        self.stdout.write("Inventory ledger audit passed; no data changed.")
