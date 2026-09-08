"""Audit cutover candidates and the posted ledger in one read-only snapshot."""

from importlib import import_module

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import connection, transaction

from apps.purchasing.models import LegacyReceiptAdjustment
from apps.purchasing.services.stock_movement_service import inventory_audit_findings


class Command(BaseCommand):
    """Expose recurring inventory reconciliation to deployment operators."""

    help = "Audit inventory openings, balances, costs, reversals and net receipts without writes."

    def add_arguments(self, parser: CommandParser) -> None:
        """Allow source validation before the complete ledger schema has been installed."""
        parser.add_argument("--preflight-only", action="store_true")

    def handle(self, *_args: object, **_options: object) -> None:
        """Validate candidates and report ledger discrepancies without repairs."""
        migration = import_module("apps.purchasing.migrations.0011_backfill_job_openings")
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            cursor.execute(migration.PREFLIGHT_SQL)
            if _options["preflight_only"]:
                self.stdout.write(
                    "Inventory cutover source preflight passed; full audit still required."
                )
                return
            cursor.execute("""
                SELECT count(*), sum(c.quantity * c.unit_cost), sum(c.quantity * c.unit_rev)
                FROM job_costline c JOIN job_costset cs ON cs.id = c.cost_set_id
                WHERE cs.kind = 'actual' AND c.kind = 'material' AND c.approved
                  AND c.ext_refs ? 'stock_id'
                  AND NOT EXISTS (
                      SELECT 1 FROM purchasing_stockmovement m WHERE m.cost_line_id = c.id
                  )
            """)
            self.stdout.write(f"Pending job openings (count, cost, revenue): {cursor.fetchone()}")
            findings = inventory_audit_findings()
            self.stdout.write(
                f"Acknowledged legacy receipt gaps: {LegacyReceiptAdjustment.objects.count()} "
                "(missing history remains documented; these are not receipt movements)."
            )
            for label, rows in findings.items():
                self.stdout.write(f"{label}: {len(rows)} discrepancies")
                for row in rows:
                    self.stdout.write(f"  {row}")
            if findings:
                raise CommandError("Inventory audit failed; no data changed.")
        self.stdout.write("Inventory opening preflight and ledger audit passed; no data changed.")
