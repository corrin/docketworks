#!/usr/bin/env python3
"""Verify that a production-to-nonprod dump is readable and credential-free."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path

STAFF_TABLE = "accounts_staff"

PRIVATE_CONFIG_TABLES = (
    "workflow_aiprovider",
    "workflow_xeroapp",
    "workflow_serviceapikey",
    "crm_phoneprovidersettings",
    "quoting_suppliercredential",
)


def _pg_restore(archive: Path, *args: str) -> str:
    pg_restore = shutil.which("pg_restore")
    if pg_restore is None:
        raise RuntimeError("pg_restore is not installed or not on PATH")
    result = subprocess.run(  # noqa: S603 -- fixed argv; executable resolved via shutil.which, no user input
        [pg_restore, *args, str(archive)],
        capture_output=True,
        check=False,
        text=True,
    )
    if result.returncode:
        operation = " ".join(args) or "archive read"
        raise RuntimeError(f"pg_restore {operation} failed with exit code {result.returncode}")
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


def _column_values(archive: Path, table: str, column: str) -> list[str]:
    """Every value of one column, read out of the archive's COPY block.

    pg_dump names the columns in the ``COPY x (a, b, c) FROM stdin;`` header,
    so the position is read from the archive rather than assumed — a column
    added or reordered by a migration would otherwise silently shift which
    field this inspects.
    """
    sql = _pg_restore(archive, "--data-only", f"--table={table}", "--file=-")
    header = next((line for line in sql.splitlines() if line.startswith("COPY ")), None)
    if header is None:
        raise RuntimeError(f"Required table data entry is missing: {table}")
    columns = [name.strip() for name in header.split("(", 1)[1].split(")", 1)[0].split(",")]
    if column not in columns:
        raise RuntimeError(f"{table} has no {column} column; the archive's schema has moved")
    index = columns.index(column)
    return [row.split("\t")[index] for row in _copy_rows(sql)]


def distinct_usable_hashes(passwords: Iterable[str]) -> int:
    """How many different real password hashes a column holds.

    Django writes ``!``-prefixed values for unusable passwords, so those are
    not hashes anyone can log in with. The scrub leaves at most one distinct
    usable value (one shared hash of the public nonprod password); production
    salts per row, so unscrubbed data shows up as many.
    """
    return len({value for value in passwords if value and not value.startswith("!")})


def _assert_passwords_scrubbed(archive: Path) -> None:
    """Fail a v2-produced archive that still carries real password hashes.

    The scrub replaces every staff password with one shared hash of the public
    nonprod password, so a clean archive holds at most one distinct usable
    value; production hashes are per-row salted and show up as many. Checked
    without Django so this stays a plain archive reader.

    Warns rather than fails for a v1-produced archive: v1's scrubber left the
    hashes, and refusing those would block every restore until production runs
    v2. The warning is the operator's cue to delete the file after restoring.
    """
    distinct = distinct_usable_hashes(_column_values(archive, STAFF_TABLE, "password"))
    if distinct <= 1:
        return

    detail = f"{distinct} distinct usable password hashes in {STAFF_TABLE}"
    if _is_v2_ledger(_table_rows(archive, "django_migrations")):
        raise RuntimeError(
            f"Backup carries unscrubbed password hashes ({detail}). The scrub replaces "
            "every staff password; this archive was not scrubbed by that code."
        )
    print(
        f"WARNING: {detail} — this archive was produced by the v1 host, whose scrubber "
        "left password hashes in place. Delete the file once the restore is done.",
        file=sys.stderr,
    )


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


def _is_v2_ledger(rows: list[str]) -> bool:
    """True when the migration ledger was written by a v2 installation.

    A v2 ledger carries ``company/0001_initial`` and no ``workflow`` app at
    all — every v1 era had workflow migrations, v2 never does (its models
    moved to other apps with the tables pinned by ``db_table``).
    """
    apps_seen: set[str] = set()
    has_company_initial = False
    for row in rows:
        columns = row.split("\t")
        if len(columns) < 3:
            continue
        app, migration = columns[1:3]
        apps_seen.add(app)
        if app == "company" and migration == "0001_initial":
            has_company_initial = True
    return has_company_initial and "workflow" not in apps_seen


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
        raise RuntimeError("Backup has mixed client/company 0001_baseline migration labels")
    # No baseline entry at all is fine for an archive v2's own producer wrote
    # (post-cutover pulls): a v2 ledger never held the squash baseline. Only a
    # baseline-less ledger that still looks like v1 predates the squash.
    if _is_v2_ledger(rows):
        return
    raise RuntimeError(
        "Backup predates the July migration squash: no company 0001_baseline ledger entry"
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

    _assert_passwords_scrubbed(archive)

    populated: list[str] = []
    for table in PRIVATE_CONFIG_TABLES:
        count = len(_table_rows(archive, table))
        if count:
            populated.append(f"{table}={count}")
    if populated:
        raise RuntimeError(
            "Backup contains private external-system configuration: " + ", ".join(populated)
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
