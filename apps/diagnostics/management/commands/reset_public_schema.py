"""Drop and recreate the default database's public schema — the sanctioned wipe.

The restore runbooks (dev/UAT refreshes, E2E snapshot recovery, production
commissioning) need "empty the target database" as a step. A raw
``dbshell -- -c "DROP SCHEMA public CASCADE"`` was rejected as the process:
it carries no refusals and no statement of intent, so neither a reviewer nor
a permission layer can tell the runbook's reset from an agent mistake.

The capability model (ADR 0048): a role may wipe only what it owns —
postgres ownership enforces that — and this command grades the
deliberateness required by what the DB name says the target is. The name is
the one signal an agent cannot usefully spoof: wiping a database requires
connecting to it. Classes:

- TEST (``test_*`` or ``*_test``): synthetic data by construction — allowed,
  no snapshot by default (``--backup`` opts in).
- APP non-prod (everything else not ending ``_prod``): ``--database`` must
  name the target; a pre-wipe snapshot is taken by default
  (``--skip-backup`` opts out).
- APP prod (``*_prod``): additionally requires ``--wipe-production`` — the
  explicit assertion only production-purpose runbooks carry, so a
  copy-pasted dev/UAT line fails — and the snapshot is mandatory
  (``--skip-backup`` refused): a production wipe is always recoverable by
  construction. Agents legitimately operate in production (PVT), so there
  is deliberately no flat refusal.

The snapshot rides the shared scrub-pipeline plumbing (ADR 0039):
``require_pg_tools`` resolves absolute tool paths upfront, ``DbConnection``
carries validated connection fields, and ``pg_dump -Z6`` writes
gzip-compressed plain SQL in one process — no shell pipe, one exit code,
restorable with the runbook's ``gunzip -c | psql --single-transaction``
contract.
"""

import os
import subprocess
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import connection
from django.utils import timezone

from apps.core.environment import database_class
from apps.diagnostics.services import scrub_pipeline


def _backup_dir(db_name: str) -> Path:
    """Resolve the provisioned instance backup dir, else <checkout>/backups.

    On instances the checkout is a root-owned release symlink, so a relative
    ``backups/`` write would die with PermissionError; the writable location
    is the per-instance directory instance.sh provisions
    (``/opt/docketworks/instances/<client>-<env>/backups``).
    """
    instance = db_name.removeprefix("dw_").replace("_", "-")
    instance_dir = Path("/opt/docketworks/instances") / instance / "backups"
    if instance_dir.is_dir():
        return instance_dir
    checkout_dir = Path(settings.BASE_DIR) / "backups"
    checkout_dir.mkdir(parents=True, exist_ok=True)
    return checkout_dir


class Command(BaseCommand):
    """Reset the default database's public schema for a restore."""

    help = (
        "Drop and recreate the public schema of the default database. "
        "--database must match DB_NAME; prod additionally needs "
        "--wipe-production and always snapshots first."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        """Declare the confirmation and tier flags."""
        parser.add_argument(
            "--database",
            required=True,
            help="The configured DB_NAME, typed out — the confirmation that names the target.",
        )
        parser.add_argument(
            "--wipe-production",
            action="store_true",
            help="Required when the database name ends _prod. Only production-purpose "
            "runbooks (PVT/commissioning) document this flag.",
        )
        parser.add_argument(
            "--skip-backup",
            action="store_true",
            help="Skip the pre-wipe snapshot (refused for _prod databases).",
        )
        parser.add_argument(
            "--backup",
            action="store_true",
            help="Take a snapshot even for a test-class database.",
        )

    def handle(self, *_args: object, **options: object) -> None:
        """Refuse, snapshot, then wipe — in that order."""
        named = options["database"]
        if not isinstance(named, str):
            raise TypeError("The database option must be a string")

        configured = str(settings.DATABASES["default"]["NAME"])
        if named != configured:
            raise CommandError(
                f"--database {named!r} does not match the configured DB_NAME "
                f"({configured!r}). Name the exact database this run is meant to wipe."
            )

        klass = database_class(configured)
        if klass == "prod" and not options["wipe_production"]:
            raise CommandError(
                f"{configured} is a production database. Wiping it requires the "
                f"explicit --wipe-production flag; find it only in the "
                f"production-purpose runbook you are following, never add it to "
                f"a dev/UAT procedure."
            )
        if klass == "prod" and options["skip_backup"]:
            raise CommandError(
                "--skip-backup is refused for a production database: a prod wipe "
                "must always be recoverable from its own pre-wipe snapshot."
            )

        wants_snapshot = (
            (klass == "test" and bool(options["backup"]))
            or (klass == "nonprod" and not options["skip_backup"])
            or klass == "prod"
        )
        if wants_snapshot:
            snapshot = self._snapshot()
            self.stdout.write(f"Pre-wipe snapshot: {snapshot}")
            self.stdout.write(
                "Restore with: uv run python manage.py reset_public_schema "
                f'--database "{configured}" --skip-backup && '
                f'gunzip -c "{snapshot}" | psql -v ON_ERROR_STOP=1 '
                f'--single-transaction -d "{configured}"'
            )
        else:
            self.stdout.write("No snapshot (test-class database or --skip-backup).")

        with connection.cursor() as cursor:
            cursor.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        self.stdout.write(self.style.SUCCESS(f"Reset public schema on {configured}"))

    def _snapshot(self) -> Path:
        """Dump the database, or abort the whole command — never wipe undumped."""
        tools = scrub_pipeline.require_pg_tools()
        db = scrub_pipeline.connection_fields("default")

        ts = timezone.localtime().strftime("%Y%m%d_%H%M%S")
        target = _backup_dir(db.name) / f"pre_reset_{db.name}_{ts}.sql.gz"
        tmp = target.with_suffix(".gz.tmp")

        env = os.environ.copy()
        env["PGPASSWORD"] = db.password
        try:
            scrub_pipeline.run(
                [
                    tools.pg_dump,
                    "-h",
                    db.host,
                    "-U",
                    db.user,
                    "-d",
                    db.name,
                    "-Z",
                    "6",
                    "-f",
                    str(tmp),
                ],
                env=env,
            )
        except subprocess.CalledProcessError as exc:
            tmp.unlink(missing_ok=True)
            raise CommandError(
                f"Pre-wipe snapshot failed — refusing to wipe {db.name}. "
                f"pg_dump exited {exc.returncode}; its error is above."
            ) from exc
        if not tmp.exists() or tmp.stat().st_size == 0:
            tmp.unlink(missing_ok=True)
            raise CommandError(f"Pre-wipe snapshot is empty — refusing to wipe {db.name}.")
        tmp.replace(target)
        return target
