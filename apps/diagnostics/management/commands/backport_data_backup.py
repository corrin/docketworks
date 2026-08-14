"""Produce a scrubbed pg_dump of production for non-production refresh.

Ported from v1's ``apps/workflow/management/commands/backport_data_backup.py``
minus the legacy ``--analyze-fields`` diagnostic (a dumpdata field sampler
that predates the pipeline and inspected the live DB; the PII contract is now
pinned by ``scripts/ops/verify_scrubbed_backup.py`` and the scrubber tests).

Pipeline: drop/recreate the scrub database's public schema, pipe ``pg_dump``
of the live DB straight into ``pg_restore`` on the scrub DB (raw production
data never lands on disk), scrub in place, snapshot ``django_migrations`` to
a ``<output>.migrations.json`` sidecar (consumed by
``scripts/ops/migrate_to_snapshot.py``), re-dump the scrubbed copy, then
empty the scrub schema again. The consumer-side acceptance check is
``scripts/ops/verify_scrubbed_backup.py``.
"""

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import connections

from apps.core.errors import AppErrorContext, persist_app_error
from apps.diagnostics.services import db_scrubber, scrub_pipeline


class Command(BaseCommand):
    """Pipe prod through the scrub database and write a scrubbed archive."""

    help = (
        "Produces a scrubbed pg_dump of prod for dev refresh. "
        "Raw prod data never leaves the prod host. Also writes a "
        "<output>.migrations.json snapshot of django_migrations beside the "
        "archive."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        """Add the optional explicit output path."""
        parser.add_argument(
            "--output",
            type=str,
            default=None,
            help=(
                "Write the scrubbed dump to this exact path. "
                "Default: <BASE_DIR>/restore/scrubbed_<DB_NAME>_<timestamp>.dump"
            ),
        )

    def handle(self, *_args: object, **options: object) -> None:
        """Run the dump-scrub-redump pipeline."""
        output = options.get("output")
        if output is not None and not isinstance(output, str):
            raise TypeError("The output option must be a string")

        # Every refusal comes BEFORE the first destructive step.
        tools = scrub_pipeline.require_pg_tools()
        default_db, scrub_db = scrub_pipeline.require_scrub_config()
        scrubbed_dump = scrub_pipeline.resolve_output_path(output, f"scrubbed_{default_db['NAME']}")

        env = os.environ.copy()
        env["PGPASSWORD"] = str(default_db["PASSWORD"])

        try:
            self.stdout.write(f"drop/recreate public schema on {scrub_db['NAME']}")
            scrub_pipeline.reset_scrub_schema(tools.psql, scrub_db, env)

            # Pipe pg_dump → pg_restore so raw prod data never lands on disk.
            self.stdout.write(f"pg_dump {default_db['NAME']} | pg_restore -> {scrub_db['NAME']}")
            scrub_pipeline.run_pipe(
                [
                    tools.pg_dump,
                    "-Fc",
                    "-h",
                    str(default_db["HOST"]),
                    "-U",
                    str(default_db["USER"]),
                    "-d",
                    str(default_db["NAME"]),
                ],
                [
                    tools.pg_restore,
                    "--no-owner",
                    "--no-privileges",
                    "--exit-on-error",
                    "-h",
                    str(scrub_db["HOST"]),
                    "-U",
                    str(scrub_db["USER"]),
                    "-d",
                    str(scrub_db["NAME"]),
                ],
                env=env,
            )

            self.stdout.write("db_scrubber.scrub()")
            db_scrubber.scrub()

            snapshot_path = self._write_migrations_snapshot(scrubbed_dump)
            self.stdout.write(f"migrations snapshot written: {snapshot_path}")

            self.stdout.write(f"pg_dump {scrub_db['NAME']} -> {scrubbed_dump}")
            scrub_pipeline.run(
                [
                    tools.pg_dump,
                    "-Fc",
                    "-h",
                    str(scrub_db["HOST"]),
                    "-U",
                    str(scrub_db["USER"]),
                    "-d",
                    str(scrub_db["NAME"]),
                    "-f",
                    str(scrubbed_dump),
                ],
                env=env,
            )

            # Reset again so no scrubbed-but-undumped copy lingers in scratch.
            self.stdout.write(f"drop/recreate public schema on {scrub_db['NAME']}")
            scrub_pipeline.reset_scrub_schema(tools.psql, scrub_db, env)

            self.stdout.write(self.style.SUCCESS(f"Scrubbed dump written: {scrubbed_dump}"))
        except Exception as exc:
            persist_app_error(
                exc,
                AppErrorContext(
                    additional_context={"operation": "backport_data_backup"},
                ),
            )
            raise

    def _write_migrations_snapshot(self, dump_path: Path) -> Path:
        """Snapshot django_migrations from the scrub DB beside the archive.

        Read from the scrub alias, not default, so the snapshot describes
        exactly the ledger the archive carries. Format matches what
        ``scripts/ops/migrate_to_snapshot.py`` consumes (v1's
        ``create_migrations_snapshot`` payload): ``{"dumped_at", "rows":
        [{"app", "name", "applied"}]}``.
        """
        snapshot_path = Path(f"{dump_path}.migrations.json")
        with connections[db_scrubber.SCRUB_ALIAS].cursor() as cur:
            cur.execute("SELECT app, name, applied FROM django_migrations ORDER BY id")
            rows = [
                {"app": app, "name": name, "applied": applied.isoformat()}
                for app, name, applied in cur.fetchall()
            ]
        if not rows:
            raise CommandError("django_migrations in the scrub DB holds zero rows")
        payload = {
            "dumped_at": datetime.now(UTC).isoformat(),
            "rows": rows,
        }
        snapshot_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return snapshot_path
