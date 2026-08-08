"""Sync all PostgreSQL sequences to match actual table data.

Called by the Playwright E2E DB lifecycle (frontend/tests/scripts/) before
backup and after restore, because a psql dump replay can leave sequences
behind the data. Django's ``sqlsequencereset`` is used rather than raw
``setval`` SQL because it already handles both serial and identity columns
across every installed app.

``scripts/ops/migrate_v1_data.sh`` carries its own raw-SQL version of this
concept and deliberately keeps it: that script is the rehearsed cutover path
and must keep working without a Django environment, so it is frozen until
after cutover rather than rewired through this command days before the date.
"""

from io import StringIO
from typing import Any

from django.apps import apps
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    """Reset every app's sequences to match current table contents."""

    help = "Sync all PostgreSQL sequences to match actual table data"

    def handle(self, *args: Any, **options: Any) -> None:  # noqa: ARG002 -- BaseCommand signature
        """Collect sqlsequencereset SQL for all apps and execute it."""
        app_labels = [c.label for c in apps.get_app_configs()]
        sql_output = StringIO()
        call_command("sqlsequencereset", "--no-color", *app_labels, stdout=sql_output)
        sql = sql_output.getvalue().strip()
        if not sql:
            self.stdout.write("No sequences to sync.")
            return
        with connection.cursor() as cursor:
            cursor.execute(sql)
        self.stdout.write("All sequences synced.")
