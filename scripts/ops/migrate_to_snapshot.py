#!/usr/bin/env python
"""Apply Django migrations up to the state recorded in a migrations.json snapshot.

The snapshot is produced by v1's `manage.py backport_data_backup` (see
`create_migrations_snapshot`) and ships inside the prod backup zip that
scripts/ops/pull_prod_backup.sh fetches.

Usage:
    uv run python -m scripts.ops.migrate_to_snapshot <path-to-migrations.json>

For each app in the snapshot this script calls
`manage.py migrate <app> <latest_name>` so that the local DB ends up with the
exact schema prod had at backup time. Django resolves cross-app dependencies;
any dependency it pulls in is also in the snapshot, so the closure is
self-consistent. After the loop the script re-reads django_migrations and
fails loudly if any row does not match the snapshot.
"""

import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import TypedDict

from scripts.bootstrap import setup_django

setup_django()

from django.db import connection  # noqa: E402 -- Django must be configured first

from apps.core.errors import AppErrorContext, persist_app_error  # noqa: E402

# Where manage.py lives; the migrate subprocesses must run from here.
REPO_ROOT = Path(__file__).resolve().parent.parent.parent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("migrate_to_snapshot")


class MigrationRow(TypedDict):
    """One applied-migration record from the snapshot."""

    app: str
    name: str


def load_snapshot(path: Path) -> list[MigrationRow]:
    """Read the snapshot's rows, refusing an empty snapshot."""
    with path.open(encoding="utf-8") as f:
        payload = json.load(f)
    rows: list[MigrationRow] = payload["rows"]
    if not rows:
        raise ValueError(f"Snapshot {path} contains zero migration rows")
    return rows


def latest_per_app(rows: list[MigrationRow]) -> dict[str, str]:
    """The lexically-latest migration name per app (Django's naming sorts)."""
    latest: dict[str, str] = {}
    for row in rows:
        app = row["app"]
        name = row["name"]
        if app not in latest or name > latest[app]:
            latest[app] = name
    return latest


def apply_target(app: str, name: str) -> None:
    """Run `manage.py migrate <app> <name>` in a subprocess, failing loudly."""
    logger.info("migrate %s %s", app, name)
    subprocess.run(  # noqa: S603 -- app/name come from the operator-supplied snapshot, not the network
        [sys.executable, "manage.py", "migrate", app, name],
        check=True,
        cwd=REPO_ROOT,
    )


def read_current_state() -> set[tuple[str, str]]:
    """Read (app, name) pairs straight from django_migrations."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT app, name FROM django_migrations")
        return {(app, name) for app, name in cursor.fetchall()}


def verify_matches_snapshot(rows: list[MigrationRow]) -> None:
    """Fail loudly if django_migrations diverges from the snapshot at all."""
    snapshot_pairs = {(row["app"], row["name"]) for row in rows}
    current_pairs = read_current_state()

    missing = snapshot_pairs - current_pairs
    extra = current_pairs - snapshot_pairs

    if missing or extra:
        raise RuntimeError(
            "Post-migrate django_migrations does not match snapshot. "
            f"Missing {len(missing)} rows (e.g. {sorted(missing)[:5]}). "
            f"Extra {len(extra)} rows (e.g. {sorted(extra)[:5]})."
        )


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("Usage: uv run python -m scripts.ops.migrate_to_snapshot <migrations.json>")

    path = Path(sys.argv[1])
    if not path.exists():
        sys.exit(f"Snapshot not found: {path}")

    rows = load_snapshot(path)
    targets = latest_per_app(rows)
    logger.info("Snapshot has %d rows across %d apps", len(rows), len(targets))

    try:
        for app, name in sorted(targets.items()):
            apply_target(app, name)
        verify_matches_snapshot(rows)
    except Exception as exc:
        # Unexpected mid-restore failure: persist with the snapshot path so
        # the AppError row identifies which restore attempt broke, then
        # re-raise — a partial migration state must never look like success.
        persist_app_error(exc, AppErrorContext(additional_context={"snapshot": str(path)}))
        raise

    logger.info("Local django_migrations matches snapshot (%d rows)", len(rows))


if __name__ == "__main__":
    main()
