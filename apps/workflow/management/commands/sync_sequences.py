"""Sync all PostgreSQL sequences to match actual table data."""

import logging
from io import StringIO

from django.apps import apps
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import connection

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Sync all PostgreSQL sequences to match actual table data"

    def handle(self, *args, **options):
        app_labels = [c.label for c in apps.get_app_configs()]
        sql_output = StringIO()
        call_command(
            "sqlsequencereset",
            "--no-color",
            *app_labels,
            stdout=sql_output,
        )
        sql = sql_output.getvalue().strip()
        if sql:
            with connection.cursor() as cursor:
                cursor.execute(sql)
        self.stdout.write("All sequences synced.")
