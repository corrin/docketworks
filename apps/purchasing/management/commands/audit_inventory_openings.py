"""Audit cutover candidates and the posted ledger in one read-only snapshot."""

from importlib import import_module

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import connection, transaction
from django.db.migrations.recorder import MigrationRecorder

from apps.purchasing.services.stock_movement_service import inventory_audit_findings

#: The movement tables arrive with this migration, and a database restored from production
#: predates it — which is precisely when an operator runs the preflight, before an
#: unattended migrate. So the checks that read movements cannot be asked there at all, and
#: naming the migration says so from the record rather than by probing for a table.
LEDGER_SCHEMA_MIGRATION = (
    "purchasing",
    "0006_stockmovement_stocktake_stocktakeconfiguration_and_more",
)


class Command(BaseCommand):
    """Expose recurring inventory reconciliation to deployment operators."""

    help = "Audit inventory openings, balances, costs, reversals and net receipts without writes."

    def add_arguments(self, parser: CommandParser) -> None:
        """Allow source validation before the complete ledger schema has been installed."""
        parser.add_argument("--preflight-only", action="store_true")

    def handle(self, *_args: object, **_options: object) -> None:
        """Validate candidates and report ledger discrepancies without repairs."""
        openings = import_module("apps.purchasing.migrations.0011_backfill_job_openings")
        reconciliation = import_module(
            "apps.purchasing.migrations.0007_reconcile_duplicated_receipt_balances"
        )
        app, name = LEDGER_SCHEMA_MIGRATION
        ledger_installed = (
            MigrationRecorder(connection).migration_qs.filter(app=app, name=name).exists()
        )
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            # 0015 refuses an order line holding more evidence than it received, and 0007
            # empties the duplicated balance behind it. Both run inside migrate, where a
            # refusal costs a half-migrated instance, so this projection comes first: it
            # reads only the pre-cutover tables and is therefore the one check available
            # at the moment the answer is worth having.
            cursor.execute(reconciliation.OVER_EVIDENCED_SQL)
            duplicated = cursor.fetchall()
            for row in duplicated:
                self.stdout.write(f"  Duplicated receipt balance: {row}")
            if len(duplicated) > reconciliation.DUPLICATED_BALANCE_LIMIT:
                raise CommandError(
                    f"{len(duplicated)} order lines hold more evidence than they received, "
                    f"above the ceiling of {reconciliation.DUPLICATED_BALANCE_LIMIT}; "
                    "the cutover will refuse them."
                )
            self.stdout.write(
                f"Duplicated receipt balances the cutover will empty: {len(duplicated)}"
            )
            if not ledger_installed:
                self.stdout.write(
                    "Ledger tables are not installed yet, so movement evidence cannot be "
                    "read here; migrate installs them and runs those checks itself."
                )
                return
            cursor.execute(openings.PREFLIGHT_SQL)
            # The pending-openings figure is what the operator checks the backfill against,
            # so it is printed before the preflight-only exit: after the backfill runs the
            # same query necessarily returns zero and the number can no longer be obtained.
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
            if _options["preflight_only"]:
                self.stdout.write(
                    "Inventory cutover source preflight passed; full audit still required."
                )
                return
            findings = inventory_audit_findings()
            for label, rows in findings.items():
                self.stdout.write(f"{label}: {len(rows)} discrepancies")
                for row in rows:
                    self.stdout.write(f"  {row}")
            if findings:
                raise CommandError("Inventory audit failed; no data changed.")
        self.stdout.write("Inventory opening preflight and ledger audit passed; no data changed.")
