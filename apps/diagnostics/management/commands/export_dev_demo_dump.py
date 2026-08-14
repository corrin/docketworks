"""Produce a lightly scrubbed pg_dump of a dev database for a trusted demo.

Pipeline (shared plumbing in ``apps.diagnostics.services.scrub_pipeline``):
restore a copy of the dev DB into the scratch ``scrub`` database, apply the
dev-demo scrub policy there, dump the scrubbed copy, then reset the scratch
schema. The source database is never written. The scrub POLICY is
``dev_demo_export_scrubber`` — deliberately lighter than the production
``db_scrubber``, which answers a different threat model.
"""

import os

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.core.errors import persist_app_error
from apps.diagnostics.services import scrub_pipeline
from apps.diagnostics.services.dev_demo_export_scrubber import scrub_dev_demo_export


class Command(BaseCommand):
    """Dump, scrub and re-dump the dev database for external demo use."""

    help = "Produces a lightly scrubbed pg_dump of dev for a trusted external data warehouse demo."

    def add_arguments(self, parser: CommandParser) -> None:
        """Declare the optional output path."""
        parser.add_argument(
            "--output",
            type=str,
            default=None,
            help=(
                "Write the demo dump to this exact path. "
                "Default: <BASE_DIR>/restore/dev_demo_<DB_NAME>_<timestamp>.dump"
            ),
        )

    def handle(self, *_args: object, **options: object) -> None:
        """Run the dump-scrub-redump pipeline, persisting unexpected failures."""
        output = options["output"]
        if output is not None and not isinstance(output, str):
            raise TypeError("The output option must be a string")

        tools = scrub_pipeline.require_pg_tools()
        default_db, scrub_db = scrub_pipeline.require_scrub_config()

        source_name = default_db.name
        scrub_name = scrub_db.name
        # Beyond the shared config checks: this export is for DEV data only.
        if not source_name.endswith("_dev"):
            raise CommandError(
                f"DB_NAME ({source_name!r}) must end in '_dev'. "
                "Refusing to export a non-dev database."
            )

        demo_dump = scrub_pipeline.resolve_output_path(output, f"dev_demo_{source_name}")

        env = os.environ.copy()
        env["PGPASSWORD"] = default_db.password

        try:
            self.stdout.write(f"drop/recreate public schema on {scrub_name}")
            scrub_pipeline.reset_scrub_schema(tools.psql, scrub_db, env)

            self.stdout.write(f"pg_dump {source_name} | pg_restore -> {scrub_name}")
            scrub_pipeline.run_pipe(
                [
                    tools.pg_dump,
                    "-Fc",
                    "-h",
                    default_db.host,
                    "-U",
                    default_db.user,
                    "-d",
                    source_name,
                ],
                [
                    tools.pg_restore,
                    "--no-owner",
                    "--no-privileges",
                    "--exit-on-error",
                    "-h",
                    scrub_db.host,
                    "-U",
                    scrub_db.user,
                    "-d",
                    scrub_name,
                ],
                env=env,
            )

            self.stdout.write("dev_demo_export_scrubber.scrub_dev_demo_export()")
            for result in scrub_dev_demo_export():
                self.stdout.write(f"  {result.name}: {result.rows}")

            self.stdout.write(f"pg_dump {scrub_name} -> {demo_dump}")
            scrub_pipeline.run(
                [
                    tools.pg_dump,
                    "-Fc",
                    "-h",
                    scrub_db.host,
                    "-U",
                    scrub_db.user,
                    "-d",
                    scrub_name,
                    "-f",
                    str(demo_dump),
                ],
                env=env,
            )

            # Reset again so no scrubbed-but-undumped copy lingers in scratch.
            self.stdout.write(f"drop/recreate public schema on {scrub_name}")
            scrub_pipeline.reset_scrub_schema(tools.psql, scrub_db, env)
        except Exception as exc:
            persist_app_error(exc)
            raise

        self.stdout.write(self.style.SUCCESS(f"Demo dump written: {demo_dump}"))
