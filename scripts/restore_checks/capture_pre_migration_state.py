#!/usr/bin/env python3
"""Capture count-only evidence from a restored pre-KAN-278 database."""

import json
import os
import sys
from pathlib import Path
from typing import TypedDict

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "docketworks.settings")

import django

django.setup()

from django.db import connection

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = REPO_ROOT / "restore" / "pre_migration_state.json"


class PreMigrationSnapshot(TypedDict):
    companies: int
    contacts: int
    contact_methods: int
    jobs: int
    calls: int
    jobs_with_contact: int
    calls_with_contact: int


def _scalar(sql: str, params: tuple[str, ...] = ()) -> int:
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        row = cursor.fetchone()
    if row is None:
        raise RuntimeError("Pre-migration query returned no row")
    return int(row[0])


def _table_exists(table: str) -> bool:
    return bool(_scalar("SELECT to_regclass(%s) IS NOT NULL", (f"public.{table}",)))


def capture_snapshot() -> PreMigrationSnapshot:
    required_tables = (
        "client_client",
        "client_clientcontact",
        "client_clientcontactmethod",
        "job_job",
        "crm_phonecallrecord",
        "django_migrations",
    )
    missing = [table for table in required_tables if not _table_exists(table)]
    if missing:
        raise RuntimeError(
            "Restored pre-migration tables are missing: " + ", ".join(missing)
        )
    if _table_exists("company_company"):
        raise RuntimeError(
            "company_company already exists; expected the pre-KAN-278 client schema"
        )
    baseline_count = _scalar(
        "SELECT COUNT(*) FROM django_migrations WHERE app = %s AND name = %s",
        ("client", "0001_baseline"),
    )
    if baseline_count != 1:
        raise RuntimeError(
            "Expected exactly one client.0001_baseline migration ledger row; "
            f"found {baseline_count}"
        )

    snapshot: PreMigrationSnapshot = {
        "companies": _scalar("SELECT COUNT(*) FROM client_client"),
        "contacts": _scalar("SELECT COUNT(*) FROM client_clientcontact"),
        "contact_methods": _scalar("SELECT COUNT(*) FROM client_clientcontactmethod"),
        "jobs": _scalar("SELECT COUNT(*) FROM job_job"),
        "calls": _scalar("SELECT COUNT(*) FROM crm_phonecallrecord"),
        "jobs_with_contact": _scalar(
            "SELECT COUNT(*) FROM job_job WHERE contact_id IS NOT NULL"
        ),
        "calls_with_contact": _scalar(
            "SELECT COUNT(*) FROM crm_phonecallrecord WHERE contact_id IS NOT NULL"
        ),
    }
    if not snapshot["companies"] or not snapshot["jobs"]:
        raise RuntimeError(
            "Restored production snapshot must contain companies and jobs"
        )
    return snapshot


def main(argv: list[str]) -> int:
    if len(argv) > 2:
        print(f"Usage: {argv[0]} [output.json]", file=sys.stderr)
        return 2
    output = Path(argv[1]) if len(argv) == 2 else DEFAULT_OUTPUT
    snapshot = capture_snapshot()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n")
    print(f"Pre-migration state captured: {output}")
    for name, count in snapshot.items():
        print(f"{name}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
