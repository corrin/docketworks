#!/usr/bin/env python3
"""Verify that a production-to-nonprod dump is readable and credential-free."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PRIVATE_CONFIG_TABLES = (
    "workflow_aiprovider",
    "workflow_xeroapp",
    "workflow_serviceapikey",
    "crm_phoneprovidersettings",
    "quoting_suppliercredential",
)


def _pg_restore(archive: Path, *args: str) -> str:
    result = subprocess.run(
        ["pg_restore", *args, str(archive)],
        capture_output=True,
        check=False,
        text=True,
    )
    if result.returncode:
        operation = " ".join(args) or "archive read"
        raise RuntimeError(
            f"pg_restore {operation} failed with exit code {result.returncode}"
        )
    return result.stdout


def _copy_rows(sql: str) -> list[str]:
    rows: list[str] = []
    in_copy = False
    for line in sql.splitlines():
        if line.startswith("COPY "):
            in_copy = True
        elif in_copy and line == r"\.":
            in_copy = False
        elif in_copy and not line:
            pass
        elif in_copy:
            rows.append(line)
        else:
            pass
    return rows


def _table_rows(archive: Path, table: str) -> list[str]:
    sql = _pg_restore(archive, "--data-only", f"--table={table}", "--file=-")
    if "COPY " not in sql:
        raise RuntimeError(f"Required table data entry is missing: {table}")
    return _copy_rows(sql)


def _has_squashed_baseline(rows: list[str]) -> bool:
    for row in rows:
        columns = row.split("\t")
        if len(columns) < 3:
            continue
        app, migration = columns[1:3]
        if app in {"client", "company"} and migration == "0001_baseline":
            return True
    return False


def verify_backup(archive: Path) -> None:
    if not archive.is_file():
        raise RuntimeError(f"Backup not found: {archive}")

    _pg_restore(archive, "--list")
    migration_rows = _table_rows(archive, "django_migrations")
    if not _has_squashed_baseline(migration_rows):
        raise RuntimeError(
            "Backup predates the July migration squash: no client/company "
            "0001_baseline ledger entry"
        )

    populated: list[str] = []
    for table in PRIVATE_CONFIG_TABLES:
        count = len(_table_rows(archive, table))
        if count:
            populated.append(f"{table}={count}")
    if populated:
        raise RuntimeError(
            "Backup contains private external-system configuration: "
            + ", ".join(populated)
        )


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"Usage: {argv[0]} <scrubbed.dump>", file=sys.stderr)
        return 2

    archive = Path(argv[1])
    verify_backup(archive)
    print(f"Verified scrubbed backup: {archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
