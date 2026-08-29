"""The one producer of ``<dump>.migrations.json`` sidecars.

Every dump that leaves a host carries this snapshot of ``django_migrations``
so the restore side (``scripts/ops/migrate_to_snapshot.py``,
``scripts/ops/pull_prod_backup.sh``) knows exactly which schema state the
archive matches. The nightly ``scripts/backup_db.sh`` and the scrubbed
``backport_data_backup`` pipeline both write it through this function.
Fable: a second sidecar convention (the retired ``.sha`` release-pointer,
which no restore path ever read) is what this module exists to prevent.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

from django.db import connections


class EmptyMigrationLedgerError(Exception):
    """The source database's django_migrations table holds zero rows."""


def write_migrations_snapshot(alias: str, dump_path: Path) -> Path:
    """Snapshot ``django_migrations`` from ``alias`` beside ``dump_path``.

    Payload matches v1's ``create_migrations_snapshot`` shape —
    ``{"dumped_at", "rows": [{"app", "name", "applied"}]}`` — which is what
    ``migrate_to_snapshot.py`` consumes.
    """
    snapshot_path = Path(f"{dump_path}.migrations.json")
    with connections[alias].cursor() as cur:
        cur.execute("SELECT app, name, applied FROM django_migrations ORDER BY id")
        rows = [
            {"app": app, "name": name, "applied": applied.isoformat()}
            for app, name, applied in cur.fetchall()
        ]
    if not rows:
        raise EmptyMigrationLedgerError(
            f"django_migrations on alias {alias!r} holds zero rows; refusing to "
            "write a snapshot that would describe an unmigrated database"
        )
    payload = {
        "dumped_at": datetime.now(UTC).isoformat(),
        "rows": rows,
    }
    # Fable: tmp+rename, not a direct write — a crash mid-write would leave a
    # truncated sidecar beside a good dump, and the nightly rclone sync would
    # ship it off-site before anyone reads it.
    tmp_path = snapshot_path.with_name(snapshot_path.name + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp_path.replace(snapshot_path)
    return snapshot_path
