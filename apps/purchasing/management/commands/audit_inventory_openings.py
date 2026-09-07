"""Read the exact cutover preflight without creating any opening records."""

from importlib import import_module

from django.core.management.base import BaseCommand
from django.db import connection, transaction


class Command(BaseCommand):
    """Expose the migration's read-only preflight to deployment operators."""

    help = "Validate inventory cutover evidence in a read-only transaction."

    def handle(self, *_args: object, **_options: object) -> None:
        """Validate all candidates before reporting their unchanged booked totals."""
        migration = import_module("apps.purchasing.migrations.0011_backfill_job_openings")
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION READ ONLY")
            cursor.execute(migration.PREFLIGHT_SQL)
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
        self.stdout.write("Inventory opening preflight passed; no data changed.")
