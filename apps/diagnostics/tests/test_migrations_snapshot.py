"""The one migrations-sidecar producer and its management command.

Pins the payload contract ``migrate_to_snapshot.py`` consumes
({"dumped_at", "rows": [{"app", "name", "applied"}]}), the refusal on an
unmigrated source, and the command's refusal to describe a dump that does
not exist.
"""

import json
from datetime import datetime
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import CommandError, call_command
from django.db import DEFAULT_DB_ALIAS, connections

from apps.diagnostics.services.migrations_snapshot import (
    EmptyMigrationLedgerError,
    write_migrations_snapshot,
)

pytestmark = pytest.mark.django_db


def test_snapshot_carries_the_full_ledger_in_the_consumed_shape(tmp_path: Path) -> None:
    dump = tmp_path / "daily_20260829.sql.gz"
    dump.write_bytes(b"")

    snapshot_path = write_migrations_snapshot(DEFAULT_DB_ALIAS, dump)

    assert snapshot_path == tmp_path / "daily_20260829.sql.gz.migrations.json"
    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    datetime.fromisoformat(payload["dumped_at"])
    rows = payload["rows"]
    assert rows, "a migrated test database has applied migrations"
    for row in rows:
        assert set(row) == {"app", "name", "applied"}
        datetime.fromisoformat(row["applied"])
    with connections[DEFAULT_DB_ALIAS].cursor() as cur:
        cur.execute("SELECT count(*) FROM django_migrations")
        (ledger_count,) = cur.fetchone()
    assert len(rows) == ledger_count


def test_empty_ledger_is_refused(tmp_path: Path) -> None:
    with connections[DEFAULT_DB_ALIAS].cursor() as cur:
        cur.execute("DELETE FROM django_migrations")
    with pytest.raises(EmptyMigrationLedgerError):
        write_migrations_snapshot(DEFAULT_DB_ALIAS, tmp_path / "daily_20260829.sql.gz")


def test_command_refuses_a_missing_dump(tmp_path: Path) -> None:
    with pytest.raises(CommandError, match="does not exist"):
        call_command("snapshot_migrations", "--dump", str(tmp_path / "absent.sql.gz"))


def test_command_writes_the_sidecar_beside_a_real_dump(tmp_path: Path) -> None:
    dump = tmp_path / "daily_20260829.sql.gz"
    dump.write_bytes(b"")
    out = StringIO()

    call_command("snapshot_migrations", "--dump", str(dump), stdout=out)

    sidecar = tmp_path / "daily_20260829.sql.gz.migrations.json"
    assert sidecar.is_file()
    assert str(sidecar) in out.getvalue()
