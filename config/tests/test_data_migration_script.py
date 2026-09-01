"""Guards on the v1->v2 data-migration path (`scripts/ops/migrate_v1_data.sh`).

The cutover order is: `manage.py migrate` into an EMPTY database, then
`pg_restore` v1's data into it. That ordering has one sharp edge: a migration
that writes *data* runs before v1's rows exist, so it either does nothing
useful or — worse — writes a row the restore is about to insert again.

Seeded rows are the dangerous case. `accounts/0003` seeds a Staff row and
`job/0002` seeds the labour-subtype catalogue; v1's dump carries both, keyed
on UNIQUE columns (email, name) with different primary keys. The restore runs
`--single-transaction --exit-on-error`, so ONE collision rolls back the entire
load and cutover fails at the data step.

The script therefore clears the seeded rows immediately before restoring, and
these tests make that contract explicit: the seeds really do write (so the
clearing is necessary), the script really does clear each seeded table, and a
NEW data-writing migration cannot be added without someone deciding which
side of the restore it belongs on.
"""

import re
from pathlib import Path

import pytest
from django.apps import apps
from django.db import IntegrityError, connection, transaction

from apps.accounts.models import Staff

REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATE_SCRIPT = REPO_ROOT / "scripts" / "ops" / "migrate_v1_data.sh"

SYSTEM_AUTOMATION_EMAIL = "system.automation@docketworks.local"

# Migrations that INSERT rows a fresh install needs. Each one's table must be
# cleared by the script before the restore, because v1's dump carries the same
# rows under different primary keys.
SEEDING_MIGRATIONS = {
    ("accounts", "0003_seed_system_automation_user"),
    ("job", "0002_seed_labour_subtypes"),
    # Fable: the IntegrationSettings singleton (pk=1). Leaving it out of this
    # set is rejected because v1's row arrives under the same key and the
    # single-transaction restore rolls back whole on the collision.
    ("core", "0003_integration_settings_row"),
}

# Migrations that FIX existing rows. Being a no-op against an empty database is
# exactly what makes them dangerous here, not what makes them safe: they run
# during `migrate`, find nothing, and v1's rows arrive afterwards untouched.
# The 2026-08-05 rehearsal proved it — quoting/0002 normalised nothing and 559
# double-encoded rows landed, 500ing the product-mappings listing. The script
# must re-apply each one after the restore.
DATA_MIGRATIONS_RERUN_AFTER_RESTORE = {
    # The v1 dump has the old Staff columns (`email` and `date_joined`). The
    # cutover script rolls this migration back before pg_restore and reapplies
    # it afterwards, when it can also backfill the employment start date.
    ("accounts", "0005_staff_payroll_identity_and_employment"),
    ("quoting", "0002_normalise_input_data"),
    # Backfills Quote.number from raw_json's _quote_number (a v1 sync era
    # never wrote the column; the Xero seeding refuses numberless documents).
    ("accounting", "0003_backfill_quote_numbers_from_raw_json"),
    # The five fixed rows exist before restore, but their Job/pay-item bindings
    # cannot resolve until v1's shop jobs and payroll catalogue have landed.
    ("timesheet", "0002_seed_leave_types"),
    # Clears the Xero pay item from public-holiday time lines so they stop being
    # posted on top of the line Xero computes itself. The lines it fixes arrive
    # with the restore, so the empty-database run finds none.
    ("timesheet", "0004_public_holiday_posts_nowhere"),
    # Fable: also here, because a dump that never created the row would
    # otherwise leave the singleton absent and every get_solo() raising.
    ("core", "0003_integration_settings_row"),
    # Measures each archived recording's length from its file. The rows arrive
    # with the restore and the files with the archive copy, so the empty-
    # database run finds nothing to measure.
    ("crm", "0003_phonecallrecording_duration_ms"),
    # Derives the stored category from v1 tags; the rows it fixes arrive with
    # the restore, so the empty-database run finds none.
    ("process", "0003_backfill_categories"),
    # v1's formentry table predates updated_at (process/0002 added it with
    # auto_now=True, a Python-side default pg_restore's COPY never invokes),
    # so the restored rows land with updated_at NULL. The rows it fixes
    # arrive with the restore, so the empty-database run finds none.
    ("process", "0007_backfill_form_entry_updated_at"),
}


# Migrations the script unapplies BEFORE the restore. Restoring with them
# applied is rejected because pg_dump --data-only names every column in its
# COPY, so a renamed column aborts the single-transaction load.
UNAPPLIED_BEFORE_RESTORE = {
    ("accounts", "0004"),
    # Fable: core/0002 renamed the phone-provider columns; crm/0002 is state-only, so
    # core at 0001 is exactly v1's table.
    ("core", "0001"),
}


def test_script_unapplies_column_renames_before_restoring() -> None:
    """pg_dump names every column in its COPY, so a renamed column aborts the load."""
    script = MIGRATE_SCRIPT.read_text()
    restore_at = script.index("pg_restore --data-only")

    for app_label, target in UNAPPLIED_BEFORE_RESTORE:
        at = script.find(f"migrate {app_label} {target}")
        assert at != -1, f"{MIGRATE_SCRIPT.name} never unapplies {app_label} to {target}"
        assert at < restore_at, f"{app_label} is unapplied AFTER the restore, which is too late"


def _seeded_tables() -> dict[str, tuple[str, str]]:
    """Table name -> the migration that seeds it."""
    return {
        Staff._meta.db_table: ("accounts", "0003_seed_system_automation_user"),
        apps.get_model("job", "LabourSubtype")._meta.db_table: (
            "job",
            "0002_seed_labour_subtypes",
        ),
        apps.get_model("core", "IntegrationSettings")._meta.db_table: (
            "core",
            "0003_integration_settings_row",
        ),
    }


@pytest.mark.django_db
def test_seed_migrations_actually_write_rows() -> None:
    """The seeds are live on a migrated database.

    If this fails the seeds stopped writing, and the script's clearing step
    became dead weight — the collision it defends against cannot happen.
    """
    assert Staff.objects.filter(office_email=SYSTEM_AUTOMATION_EMAIL).exists()
    assert apps.get_model("job", "LabourSubtype")._default_manager.exists()
    assert apps.get_model("core", "IntegrationSettings")._default_manager.filter(pk=1).exists()


def test_script_clears_every_seeded_table_before_restoring() -> None:
    """Each seeded table is emptied, and before the restore, not after."""
    script = MIGRATE_SCRIPT.read_text()
    restore_at = script.index("pg_restore --data-only")

    for table, (app_label, migration) in _seeded_tables().items():
        # S608 suppressed: this greps a shell script for a statement string;
        # nothing here executes SQL.
        match = re.search(rf"DELETE FROM {table}\b|TRUNCATE {table}\b", script)  # noqa: S608
        assert match, (
            f"{table} is seeded by {app_label}/{migration} but "
            f"{MIGRATE_SCRIPT.name} never clears it; the restore will collide "
            f"on its UNIQUE key and roll back the whole load"
        )
        assert match.start() < restore_at, (
            f"{table} is cleared AFTER the restore, which is too late — "
            f"the collision aborts the restore transaction first"
        )


def test_no_unaccounted_data_writing_migrations() -> None:
    """A new data-writing migration must be classified before it ships.

    Adding one without deciding whether it seeds (and so needs clearing) is
    how the collision gets re-armed silently. Failing here is the prompt to
    add it to SEEDING_MIGRATIONS or DATA_MIGRATIONS_RERUN_AFTER_RESTORE — and
    to the script either way, because both need handling there.
    """
    found: set[tuple[str, str]] = set()
    for path in sorted(REPO_ROOT.glob("apps/*/migrations/[0-9]*.py")):
        if "RunPython" in path.read_text():
            found.add((path.parents[1].name, path.stem))

    assert found == SEEDING_MIGRATIONS | DATA_MIGRATIONS_RERUN_AFTER_RESTORE


def test_script_reapplies_data_migrations_after_the_restore() -> None:
    """Fixing rows that do not exist yet fixes nothing.

    A data migration runs during `migrate`, before the restore. The script has
    to run it again once the rows are there, or the defect it exists to remove
    survives into v2 — which is exactly what happened to quoting/0002.
    """
    script = MIGRATE_SCRIPT.read_text()
    restore_at = script.index("pg_restore --data-only")

    for app_label, migration in DATA_MIGRATIONS_RERUN_AFTER_RESTORE:
        number = migration.split("_")[0]
        needle = f"migrate {app_label} {number}"
        at = script.find(needle)
        assert at != -1, (
            f"{app_label}/{migration} rewrites existing rows, but "
            f"{MIGRATE_SCRIPT.name} never re-applies it after the restore, so "
            f"it will have run against an empty database and fixed nothing"
        )
        assert at > restore_at, (
            f"{app_label}/{migration} is re-applied BEFORE the restore, which "
            f"is the same as not re-applying it — the rows are not there yet"
        )


def test_script_clears_v1_ciphertext_after_phone_columns_are_renamed() -> None:
    """Encrypted bytes must not survive as apparently valid plaintext credentials."""
    script = MIGRATE_SCRIPT.read_text()
    restore_at = script.index("pg_restore --data-only")
    core_rename_at = script.index("migrate core 0004", restore_at)
    phone_clear_at = script.index("UPDATE crm_phoneprovidersettings", core_rename_at)
    supplier_clear_at = script.index("UPDATE quoting_suppliercredential", phone_clear_at)

    assert "phone_provider_username = NULL" in script[phone_clear_at:supplier_clear_at]
    assert "phone_provider_password = NULL" in script[phone_clear_at:supplier_clear_at]
    assert "phone_provider_base_url = NULL" in script[phone_clear_at:supplier_clear_at]
    assert "phone_provider_account_code = NULL" in script[phone_clear_at:supplier_clear_at]
    assert "username = NULL" in script[supplier_clear_at:]
    assert "password = NULL" in script[supplier_clear_at:]
    assert "api_key = NULL" in script[supplier_clear_at:]


@pytest.mark.django_db
def test_restoring_v1s_row_collides_until_the_seed_is_cleared() -> None:
    """Demonstrate the failure the clearing step exists to prevent.

    v1's dump inserts its own automation Staff row: same email, different
    primary key. This replays that insert column-for-column against a
    migrated database — it must fail while the seeded row is present, and
    succeed once the seed is cleared the way the script clears it.
    """
    v1_row_id = "ce2f4c1a-04cc-4871-988c-9092f4cb154e"  # the id in the real restore
    fields = Staff._meta.local_fields
    values = list(
        Staff.objects.filter(office_email=SYSTEM_AUTOMATION_EMAIL).values_list(
            *[f.attname for f in fields]
        )[0]
    )
    values[[f.attname for f in fields].index("id")] = v1_row_id
    columns = ", ".join(f'"{f.column}"' for f in fields)
    placeholders = ", ".join(["%s"] * len(fields))
    # S608 suppressed: the columns come from model metadata and every value is
    # bound as a parameter. Building the statement literally is the point — it
    # is what pg_restore emits.
    insert = f"INSERT INTO {Staff._meta.db_table} ({columns}) VALUES ({placeholders})"  # noqa: S608

    with pytest.raises(IntegrityError), transaction.atomic(), connection.cursor() as cur:
        cur.execute(insert, values)

    # The script's clearing step, verbatim in intent.
    Staff.objects.filter(office_email=SYSTEM_AUTOMATION_EMAIL).delete()
    with connection.cursor() as cur:
        cur.execute(insert, values)
    assert Staff.objects.filter(id=v1_row_id).exists()
