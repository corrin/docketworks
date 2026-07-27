#!/usr/bin/env python3
"""Verify that a production-to-nonprod dump is readable and credential-free."""

from __future__ import annotations

import argparse
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


def _squashed_baseline_apps(rows: list[str]) -> set[str]:
    found: set[str] = set()
    for row in rows:
        columns = row.split("\t")
        if len(columns) < 3:
            continue
        app, migration = columns[1:3]
        if app in {"client", "company"} and migration == "0001_baseline":
            found.add(app)
    return found


def _assert_squashed_baseline(rows: list[str]) -> None:
    found = _squashed_baseline_apps(rows)
    if found == {"company"}:
        return
    if found == {"client"}:
        raise RuntimeError(
            "Backup uses the obsolete client migration label; restore it with "
            "a matching pre-cutover checkout"
        )
    if found == {"client", "company"}:
        raise RuntimeError(
            "Backup has mixed client/company 0001_baseline migration labels"
        )
    raise RuntimeError(
        "Backup predates the July migration squash: no company "
        "0001_baseline ledger entry"
    )


def verify_backup(archive: Path) -> None:
    if not archive.is_file():
        raise RuntimeError(f"Backup not found: {archive}")

    # A catalogue read does not decompress every archive entry. Rendering the
    # complete restore stream to /dev/null catches corruption anywhere in the
    # archive without creating or modifying a database.
    _pg_restore(archive, "--file=/dev/null")
    migration_rows = _table_rows(archive, "django_migrations")
    _assert_squashed_baseline(migration_rows)

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
    parser = argparse.ArgumentParser(
        prog=argv[0],
        description=__doc__,
    )
    parser.add_argument("archive", type=Path)
    args = parser.parse_args(argv[1:])
    verify_backup(args.archive)
    print(f"Verified scrubbed backup: {args.archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
