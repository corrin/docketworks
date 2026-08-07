#!/usr/bin/env python
"""Check restored v1 data against the contracts v2's models declare.

Run this after `migrate_v1_data.sh`, before trusting a load. It answers one
question: is there a row in here that v2 will refuse to save?

Three sweeps, because the database enforces only some of what the models
promise:

1. **Dangling foreign keys.** `pg_restore --disable-triggers` skips FK
   enforcement, and FK checks in PostgreSQL are triggers — so a load can
   complete with references to rows that never arrived. Nothing else catches
   this; row counts certainly do not.
2. **Missing required references.** A foreign key declared `blank=False` but
   `null=True` permits NULL in the database while the models call it
   required — checked in bulk rather than per row.
3. **Model validation.** `choices`, `blank`, `validators` and `clean()` live
   in Django's validation layer, which the write paths that produced v1's
   rows frequently did not run. Rows that violate them load fine and then
   fail the first time anyone edits them.

Foreign keys are excluded from sweep 3, deliberately. `full_clean()` issues
an existence query per foreign key per row, which on this dataset means
roughly a quarter of a million queries and a quarter of an hour — all of it
re-proving, one row at a time, what sweep 1 already proved in bulk. Sweeps 1
and 2 together cover everything `full_clean()` would have checked on an FK
column.

Deliberately NOT re-checked: CHECK constraints, NOT NULL and UNIQUE. Postgres
enforced those during the restore itself, so a load that completed is already
proof. Re-validating them costs a query per row per constraint for no
information (`validate_constraints=False` below is that decision).

Exit status is 1 when any sweep finds something, so this can gate a
cutover step rather than being read by eye.

Usage:
    uv run python -m scripts.ops.validate_restored_data [--quiet]
"""

import argparse
import os
from collections import defaultdict

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.apps import apps  # noqa: E402 -- Django must be configured first
from django.core.exceptions import ValidationError  # noqa: E402
from django.db import connection, models  # noqa: E402

EXAMPLE_CAP = 5


def _models_to_check() -> list[type[models.Model]]:
    """Every concrete model except simple-history's shadow tables.

    Historical rows mirror a real row's columns without its constraints (that
    is the point of an audit trail), so validating them reports the same
    defect twice and adds a second, unfixable copy.
    """
    return [
        model
        for model in apps.get_models()
        if not model._meta.proxy and not model.__name__.startswith("Historical")
    ]


def _fk_fields(model: type[models.Model]) -> list["models.ForeignKey[models.Model]"]:
    """This model's own foreign keys (see the note in sweep_foreign_keys)."""
    return [f for f in model._meta.local_fields if isinstance(f, models.ForeignKey)]


def sweep_required_references() -> int:
    """Count NULLs in foreign keys the models declare required (blank=False)."""
    print("\n== Sweep 2: required references that are NULL ==")
    missing = 0
    with connection.cursor() as cursor:
        for model in _models_to_check():
            for field in _fk_fields(model):
                if field.blank or not field.null:
                    continue  # optional, or the database already forbids NULL
                cursor.execute(
                    f'SELECT COUNT(*) FROM "{model._meta.db_table}" '  # noqa: S608 -- names from model metadata
                    f'WHERE "{field.column}" IS NULL'
                )
                count = cursor.fetchone()[0]
                if count:
                    missing += count
                    print(
                        f"  NULL  {model._meta.db_table}.{field.column}: {count} rows "
                        f"(declared required by {model._meta.label})"
                    )
    if not missing:
        print("  clean — every required reference is set")
    return missing


def sweep_foreign_keys() -> int:
    """Count rows whose foreign key points at a row that is not there."""
    print("== Sweep 1: dangling foreign keys ==")
    orphans = 0
    with connection.cursor() as cursor:
        for model in _models_to_check():
            table = model._meta.db_table
            # local_fields only: under multi-table inheritance an inherited FK
            # column lives on the PARENT's table, and querying it here asks
            # for a column this table does not have.
            for field in model._meta.local_fields:
                if not isinstance(field, models.ForeignKey):
                    continue
                target = field.remote_field.model._meta
                cursor.execute(
                    # Suppression below: every name comes from model metadata.
                    f'SELECT COUNT(*) FROM "{table}" t '  # noqa: S608
                    f'LEFT JOIN "{target.db_table}" r '
                    f'ON t."{field.column}" = r."{target.pk.column}" '
                    f'WHERE t."{field.column}" IS NOT NULL '
                    f'AND r."{target.pk.column}" IS NULL'
                )
                count = cursor.fetchone()[0]
                if count:
                    orphans += count
                    print(f"  ORPHANED  {table}.{field.column} -> {target.db_table}: {count} rows")
    if not orphans:
        print("  clean — every foreign key resolves")
    return orphans


def sweep_model_validation(*, quiet: bool) -> int:
    """Count rows that fail full_clean(), grouped by the message they fail with."""
    print("\n== Sweep 3: model validation ==")
    total = 0
    for model in _models_to_check():
        label = f"{model._meta.app_label}.{model.__name__}"
        failures: dict[str, list[str]] = defaultdict(list)
        count = 0
        scanned = 0
        skip = [f.name for f in _fk_fields(model)]
        for obj in model._default_manager.all().iterator(chunk_size=2000):
            scanned += 1
            try:
                # See the module docstring: uniqueness and CHECK constraints
                # were enforced by the database during the restore, and the
                # foreign keys are covered by sweeps 1 and 2 without a query
                # per row.
                obj.full_clean(exclude=skip, validate_unique=False, validate_constraints=False)
            except ValidationError as exc:
                count += 1
                key = "; ".join(
                    f"{field}: {', '.join(messages)}"
                    for field, messages in sorted(exc.message_dict.items())
                )
                if len(failures[key]) < EXAMPLE_CAP:
                    failures[key].append(str(obj.pk))
        if not quiet:
            print(f"  scanned {label}: {scanned} rows", flush=True)
        if count:
            total += count
            print(f"  FAILED  {label}: {count} of {scanned} rows")
            for message, pks in sorted(failures.items()):
                print(f"      [{message}]  e.g. {', '.join(pks)}")
    if not total:
        print("  clean — every row satisfies its model")
    return total


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--quiet", action="store_true", help="only report problems, not per-model progress"
    )
    args = parser.parse_args()

    orphans = sweep_foreign_keys()
    missing = sweep_required_references()
    invalid = sweep_model_validation(quiet=args.quiet)

    print(
        f"\nTOTALS: dangling foreign keys {orphans}, "
        f"required references NULL {missing}, rows failing validation {invalid}"
    )
    if orphans or missing or invalid:
        print("Fix the DATA, not the reader (ADR 0015).")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
