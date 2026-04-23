#!/usr/bin/env python
"""Apply Django migrations up to the state recorded in a migrations.json snapshot.

The snapshot is produced by `manage.py backport_data_backup` (see
`create_migrations_snapshot`) and ships inside the prod backup zip.

Usage:
    python scripts/migrate_to_snapshot.py <path-to-migrations.json>

For each app in the snapshot this script calls
`manage.py migrate <app> <latest_name>` so that the local DB ends up with the
exact schema prod had at backup time. Django resolves cross-app dependencies;
any dependency it pulls in is also in the snapshot, so the closure is
self-consistent. After the loop the script re-reads django_migrations and
fails loudly if any row does not match the snapshot.
"""

import json
import logging
import os
import subprocess
import sys

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "docketworks.settings")

import django  # noqa: E402

django.setup()

from django.db import connection  # noqa: E402

from apps.workflow.services.error_persistence import persist_app_error  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("migrate_to_snapshot")


def load_snapshot(path):
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    rows = payload["rows"]
    if not rows:
        raise ValueError(f"Snapshot {path} contains zero migration rows")
    return rows


def latest_per_app(rows):
    latest = {}
    for row in rows:
        app = row["app"]
        name = row["name"]
        if app not in latest or name > latest[app]:
            latest[app] = name
    return latest


def apply_target(app, name):
    logger.info("migrate %s %s", app, name)
    subprocess.run(
        ["python", "manage.py", "migrate", app, name],
        check=True,
    )


def read_current_state():
    with connection.cursor() as cursor:
        cursor.execute("SELECT app, name FROM django_migrations")
        return {(app, name) for app, name in cursor.fetchall()}


def verify_matches_snapshot(rows):
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


def main():
    if len(sys.argv) != 2:
        sys.exit("Usage: python scripts/migrate_to_snapshot.py <migrations.json>")

    path = sys.argv[1]
    if not os.path.exists(path):
        sys.exit(f"Snapshot not found: {path}")

    rows = load_snapshot(path)
    targets = latest_per_app(rows)
    logger.info("Snapshot has %d rows across %d apps", len(rows), len(targets))

    try:
        for app, name in sorted(targets.items()):
            apply_target(app, name)
        verify_matches_snapshot(rows)
    except Exception as exc:
        persist_app_error(exc)
        raise

    logger.info("Local django_migrations matches snapshot (%d rows)", len(rows))


if __name__ == "__main__":
    main()
