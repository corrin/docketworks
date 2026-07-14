#!/usr/bin/env python3
"""Verify KAN-278 preserved production-shaped data across its schema cutover."""

import json
import os
import sys
from pathlib import Path
from typing import TypedDict, TypeGuard

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "docketworks.settings")

import django

django.setup()

from django.db import connection
from django.db.models import Q

from apps.company.models import Company, CompanyPersonLink, ContactMethod, Person
from apps.crm.models import PhoneCallRecord
from apps.job.models import Job, JobEvent
from apps.workflow.models import SearchTelemetryEvent

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = REPO_ROOT / "restore" / "pre_migration_state.json"


class MigrationCounts(TypedDict):
    companies: int
    contacts: int
    contact_methods: int
    jobs: int
    calls: int
    jobs_with_contact: int
    calls_with_contact: int


COUNT_KEYS = frozenset(MigrationCounts.__annotations__)


def _is_migration_counts(value: object) -> TypeGuard[MigrationCounts]:
    if not isinstance(value, dict) or set(value) != COUNT_KEYS:
        return False
    return all(type(value[key]) is int and value[key] >= 0 for key in COUNT_KEYS)


def load_snapshot(path: Path) -> MigrationCounts:
    value: object = json.loads(path.read_text())
    if not _is_migration_counts(value):
        raise RuntimeError(f"Invalid pre-migration count artifact: {path}")
    return value


def current_counts() -> MigrationCounts:
    return {
        "companies": Company.objects.count(),
        "contacts": CompanyPersonLink.objects.count(),
        "contact_methods": ContactMethod.objects.count(),
        "jobs": Job.objects.count(),
        "calls": PhoneCallRecord.objects.count(),
        "jobs_with_contact": Job.objects.exclude(person__isnull=True).count(),
        "calls_with_contact": PhoneCallRecord.objects.exclude(
            person__isnull=True
        ).count(),
    }


def comparison_errors(before: MigrationCounts, after: MigrationCounts) -> list[str]:
    errors: list[str] = []
    preserved_counts = (
        ("companies", before["companies"], after["companies"]),
        ("jobs", before["jobs"], after["jobs"]),
        ("calls", before["calls"], after["calls"]),
        (
            "jobs_with_contact",
            before["jobs_with_contact"],
            after["jobs_with_contact"],
        ),
        (
            "calls_with_contact",
            before["calls_with_contact"],
            after["calls_with_contact"],
        ),
    )
    for name, before_count, after_count in preserved_counts:
        if before_count != after_count:
            errors.append(f"{name}: before={before_count}, after={after_count}")
    if after["contacts"] > before["contacts"]:
        errors.append(
            "company-person links increased unexpectedly: "
            f"before={before['contacts']}, after={after['contacts']}"
        )
    if after["contact_methods"] > before["contact_methods"]:
        errors.append(
            "contact methods increased unexpectedly: "
            f"before={before['contact_methods']}, after={after['contact_methods']}"
        )
    return errors


def _table_exists(table: str) -> bool:
    with connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass(%s) IS NOT NULL", [f"public.{table}"])
        row = cursor.fetchone()
    if row is None:
        raise RuntimeError("Post-migration schema query returned no row")
    return bool(row[0])


def structural_errors() -> list[str]:
    errors: list[str] = []
    required_tables = (
        "company_company",
        "company_person",
        "company_companypersonlink",
        "company_contactmethod",
    )
    old_tables = (
        "client_client",
        "client_clientcontact",
        "client_clientcontactmethod",
    )
    for table in required_tables:
        if not _table_exists(table):
            errors.append(f"required post-migration table is missing: {table}")
    for table in old_tables:
        if _table_exists(table):
            errors.append(f"legacy table still exists: {table}")

    invalid_owners = ContactMethod.objects.filter(
        Q(company__isnull=True, person__isnull=True)
        | Q(company__isnull=False, person__isnull=False)
    ).count()
    if invalid_owners:
        errors.append(f"contact methods with invalid ownership: {invalid_owners}")
    null_links = CompanyPersonLink.objects.filter(person__isnull=True).count()
    if null_links:
        errors.append(f"company-person links without a person: {null_links}")
    multi_hop_merges = Company.objects.filter(
        merged_into__merged_into__isnull=False
    ).count()
    if multi_hop_merges:
        errors.append(f"multi-hop company merges: {multi_hop_merges}")

    legacy_event_types = JobEvent.objects.filter(
        event_type__in=("client_changed", "contact_changed")
    ).count()
    if legacy_event_types:
        errors.append(f"job events with legacy event types: {legacy_event_types}")
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT COUNT(*)
            FROM job_jobevent
            WHERE detail ->> 'field_name' IN ('Client', 'Contact')
               OR detail @? '$.changes[*] ? (@.field_name == "Client" || @.field_name == "Contact")'
            """)
        row = cursor.fetchone()
    if row is None:
        raise RuntimeError("Job-event terminology query returned no row")
    if row[0]:
        errors.append(f"job events with legacy detail labels: {row[0]}")

    legacy_telemetry = SearchTelemetryEvent.objects.filter(
        Q(domain="client")
        | Q(
            source__in=(
                "client_lookup",
                "crm_clients_table",
                "crm_client_detail_phone_numbers",
            )
        )
    ).count()
    if legacy_telemetry:
        errors.append(f"telemetry rows with legacy terminology: {legacy_telemetry}")
    return errors


def verify_post_migration(snapshot: MigrationCounts) -> MigrationCounts:
    after = current_counts()
    errors = comparison_errors(snapshot, after) + structural_errors()
    people = Person.objects.count()
    if people > snapshot["contacts"]:
        errors.append(
            "people increased beyond the legacy contact population: "
            f"contacts={snapshot['contacts']}, people={people}"
        )
    if errors:
        raise RuntimeError(
            "Post-migration verification failed:\n- " + "\n- ".join(errors)
        )
    return after


def main(argv: list[str]) -> int:
    if len(argv) > 2:
        print(f"Usage: {argv[0]} [pre_migration_state.json]", file=sys.stderr)
        return 2
    source = Path(argv[1]) if len(argv) == 2 else DEFAULT_INPUT
    before = load_snapshot(source)
    after = verify_post_migration(before)
    print("Post-migration production-data invariants passed")
    for name, count in after.items():
        print(f"{name}: {count}")
    print(f"people: {Person.objects.count()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
