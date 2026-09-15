"""Hold a disposable copy of the live database in the scrub database (ADR 0064).

``load`` replaces the scrub database's contents with a snapshot of the live
one; ``empty`` drops it again. ``verify-instance.sh --e2e`` points an
instance's units at the copy for the E2E run and empties it afterwards, so
the live database is only ever read. The refusals are ``require_scrub_config``'s:
a scrub name that could be a live database, or one equal to the live one,
never reaches a ``DROP SCHEMA``.
"""

import os

from django.core.management.base import BaseCommand, CommandParser

from apps.diagnostics.services import scrub_pipeline


class Command(BaseCommand):
    """Load or empty the scrub copy of the live database."""

    help = "load: copy the live database into the scrub database; empty: drop the copy"

    def add_arguments(self, parser: CommandParser) -> None:
        """Declare the action."""
        parser.add_argument("action", choices=("load", "empty"))

    def handle(self, *_args: object, **options: object) -> None:
        """Run the requested action after every refusal."""
        action = options["action"]
        tools = scrub_pipeline.require_pg_tools()
        live_db, scrub_db = scrub_pipeline.require_scrub_config()
        env = os.environ.copy()
        env["PGPASSWORD"] = live_db.password
        if action == "load":
            self.stdout.write(f"pg_dump {live_db.name} | pg_restore -> {scrub_db.name}")
            scrub_pipeline.load_live_into_scrub(tools, live_db, scrub_db, env)
        else:
            self.stdout.write(f"drop/recreate public schema on {scrub_db.name}")
            scrub_pipeline.reset_scrub_schema(tools.psql, scrub_db, env)
        self.stdout.write(self.style.SUCCESS(f"scrub copy: {action} done ({scrub_db.name})"))
