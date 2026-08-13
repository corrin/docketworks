"""Move a database back to the migration leaves from an older release.

Consumed by scripts/rollback.sh --latest-db: the target release's leaf
migrations are captured from that release's code, then this command (run
from the CURRENT release, whose migration files cover the span being
reversed) plans and applies the reverse migrations. Refuses plans that
would migrate forward or that contain irreversible operations.
"""

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

MigrationTarget = tuple[str, str | None]


def read_migration_targets(path: Path) -> list[tuple[str, str]]:
    """Parse the tab-separated ``app<TAB>migration`` leaf list rollback.sh captures."""
    targets: list[tuple[str, str]] = []
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) != 2 or not all(parts):
            raise CommandError(f"Invalid migration target at {path}:{line_number}: {raw_line!r}")
        targets.append((parts[0], parts[1]))
    if not targets:
        raise CommandError(f"No migration targets found in {path}")
    return targets


class Command(BaseCommand):
    """Plan (default) or apply reverse migrations down to a target release's leaves."""

    help = "Plan or apply reverse migrations to an older release's leaf nodes."

    def add_arguments(self, parser: CommandParser) -> None:
        """Register --targets-file (required) and --apply."""
        parser.add_argument("--targets-file", required=True)
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args: object, **options: object) -> None:  # noqa: ARG002 -- BaseCommand signature
        """Refuse forward or irreversible plans; print the plan; migrate on --apply."""
        targets_file = options["targets_file"]
        apply_plan = options["apply"]
        if not isinstance(targets_file, str):
            raise CommandError("--targets-file must be a path")
        if not isinstance(apply_plan, bool):
            raise CommandError("--apply must be a boolean flag")

        release_targets = read_migration_targets(Path(targets_file))
        target_apps = {app_label for app_label, _ in release_targets}
        executor = MigrationExecutor(connection)
        targets: list[MigrationTarget] = list(release_targets)
        targets.extend(
            (app_label, None) for app_label in sorted(executor.loader.migrated_apps - target_apps)
        )

        plan = executor.migration_plan(targets)
        forward_migrations = [migration for migration, backwards in plan if not backwards]
        if forward_migrations:
            names = ", ".join(
                f"{migration.app_label}.{migration.name}" for migration in forward_migrations
            )
            raise CommandError(f"Target release would require forward migrations: {names}")

        irreversible = [
            migration
            for migration, _ in plan
            if not all(operation.reversible for operation in migration.operations)
        ]
        if irreversible:
            names = ", ".join(
                f"{migration.app_label}.{migration.name}" for migration in irreversible
            )
            raise CommandError(f"Irreversible migrations in rollback plan: {names}")

        if not plan:
            self.stdout.write("No migration changes required.")
            return

        for migration, _ in plan:
            self.stdout.write(f"UNAPPLY {migration.app_label}.{migration.name}")

        if apply_plan:
            executor.migrate(targets)
            self.stdout.write(self.style.SUCCESS("Reverse migrations complete."))
        else:
            self.stdout.write("Plan only; pass --apply to execute.")
