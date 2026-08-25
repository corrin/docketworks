#!/usr/bin/env bash
# One-time v1 -> v2 data migration (plan §Data migration).
#
# Usage: scripts/ops/migrate_v1_data.sh <v1_db> <v2_db> [psql-connection-args...]
#
# Preconditions: <v2_db> exists and has been freshly `manage.py migrate`d
# (empty of data beyond migration bookkeeping). Both DBs share table names by
# construction (app labels unchanged; moved models pin db_table).
#
# Steps: data-only dump of v1 (excluding infrastructure tables that v2 owns) ->
# single-transaction restore (Django FKs are DEFERRABLE INITIALLY DEFERRED on
# PostgreSQL, so circular references check at commit) -> remap contenttypes
# for models moved out of the v1 workflow app -> reset serial sequences ->
# VACUUM ANALYZE. Rehearse repeatedly; never first-run this on cutover night.
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "usage: $0 <v1_db> <v2_db> [connection args]" >&2
  exit 2
fi

V1_DB="$1"
V2_DB="$2"
shift 2

DUMP="$(mktemp --suffix=.dump)"
trap 'rm -f "$DUMP"' EXIT

echo "==> Dumping v1 data from $V1_DB"
pg_dump -Fc --data-only "$@" "$V1_DB" \
  --exclude-table=django_migrations \
  --exclude-table='django_celery_beat_*' \
  --exclude-table='django_celery_results_*' \
  --exclude-table=django_session \
  --exclude-table=django_admin_log \
  --exclude-table=django_content_type \
  --exclude-table=auth_permission \
  --exclude-table=django_site \
  --file="$DUMP"

echo "==> Clearing migration-seeded rows (v1's dump supplies them)"
# v1's accounts_staff rows use the pre-0005 columns (`email` and
# `date_joined`). Restore into that historical schema, then let the real
# migration rename and backfill those restored rows. This deliberately avoids
# maintaining a second translation implementation in this script (ADR 0039).
DB_NAME="$V2_DB" uv run python manage.py migrate accounts 0004 --no-input
# Fable: same for crm_phoneprovidersettings: core/0002 renamed its columns and added
# one, and pg_dump --data-only names every column in its COPY — even for an
# empty table — so the restore must see v1's names. crm/0002 is state-only,
# so unapplying core to 0001 returns exactly v1's table.
DB_NAME="$V2_DB" uv run python manage.py migrate core 0001 --no-input
# `manage.py migrate` seeds rows a FRESH install needs: the system automation
# Staff row (accounts/0003) and the labour-subtype catalogue (job/0002). v1's
# dump carries those same rows under different primary keys, and both collide
# on a UNIQUE column — accounts_staff.email and job_laboursubtype.name. The
# restore below runs in a single transaction, so one collision rolls back the
# ENTIRE load. v1 is authoritative on the migrated path, so the seeds go and
# the dump supplies them. Deleting rather than skipping the seeds keeps them
# working for fresh installs and the test database.
# Pinned by config/tests/test_data_migration_script.py, which fails if a new
# data-writing migration appears without being classified.
# One transaction: a failure partway through must not leave the database
# half-cleared (one seed gone, the other present) with no restore started.
psql "$@" -d "$V2_DB" -v ON_ERROR_STOP=1 <<'SQL'
BEGIN;
DELETE FROM accounts_staff WHERE email = 'system.automation@docketworks.local';
DELETE FROM job_laboursubtype;
-- Fable: core/0003 creates the IntegrationSettings row at pk=1 and v1's dump carries
-- its phone-provider row under that same key.
DELETE FROM crm_phoneprovidersettings;
COMMIT;
SQL

echo "==> Restoring into $V2_DB (single transaction; FKs are DEFERRABLE so"
echo "    circular references check at commit — no superuser needed)"
# Drop SEQUENCE SET entries: v1's sequence names are pre-rename fossils that
# don't exist in v2, and this script resets every sequence itself below.
RESTORE_LIST="$(mktemp)"
pg_restore -l "$DUMP" | grep -v 'SEQUENCE SET' > "$RESTORE_LIST"
pg_restore --data-only --single-transaction --exit-on-error -L "$RESTORE_LIST" \
  "$@" -d "$V2_DB" "$DUMP" || {
  rm -f "$RESTORE_LIST"
  echo "pg_restore failed — the transaction rolled back; nothing was loaded." >&2
  exit 1
}
rm -f "$RESTORE_LIST"

echo "==> Remapping content types for models moved out of 'workflow'"
psql "$@" -d "$V2_DB" <<'SQL'
-- v2 regenerates django_content_type/auth_permission itself (excluded from the
-- dump); FK checks were deferred to the commit of the restore transaction, so
-- remap any stale references here if a table carries content_type_id. As of
-- Phase 2 no ported table does; extend this block if one appears.
SQL

echo "==> Re-running the data-normalising migrations now the data exists"
# accounts/0005 was deliberately unapplied before the restore so pg_restore
# saw the exact v1 Staff columns. Reapply it now to rename `email`, copy
# `date_joined` into `employment_start_date`, and add the payroll identity.
DB_NAME="$V2_DB" uv run python manage.py migrate accounts 0005 --no-input
# quoting/0002 decodes v1's double-encoded ProductParsingMapping.input_data.
# It already ran during `migrate` — against an EMPTY database, where it had
# nothing to do — and v1's rows arrived afterwards, in the restore above. The
# 2026-08-05 rehearsal proved the consequence: 559 rows landed double-encoded
# and the product-mappings listing answered 500.
#
# Its reverse is a no-op, so unapplying and re-applying runs the same tested
# code with the data present. No second implementation to drift (ADR 0039).
# normalise_rows classifies every row before writing any and aborts naming the
# primary keys if one cannot be normalised, so `set -e` stops the load here
# rather than leaving a listing that 500s the first time someone opens it.
# DB_NAME is how config/settings.py picks its database; the psql-style
# connection args this script takes do not reach Django.
DB_NAME="$V2_DB" uv run python manage.py migrate quoting 0001 --no-input
DB_NAME="$V2_DB" uv run python manage.py migrate quoting 0002 --no-input
# accounting/0003 backfills Quote.number from each row's own raw_json
# _quote_number (a v1 sync era never wrote the column; the Xero seeding
# refuses numberless job-linked documents). Same shape as quoting/0002: its
# reverse is a no-op, so unapply-reapply runs the same tested code now the
# rows exist.
DB_NAME="$V2_DB" uv run python manage.py migrate accounting 0002 --no-input
DB_NAME="$V2_DB" uv run python manage.py migrate accounting 0003 --no-input
# timesheet/0002 creates the five fixed leave types during the initial empty-DB
# migrate, but it can only bind them after v1's shop Jobs and Xero pay items are
# restored. Its reverse is deliberately a no-op, so replaying it converges the
# rows without deleting any future leave data.
DB_NAME="$V2_DB" uv run python manage.py migrate timesheet 0001 --no-input
DB_NAME="$V2_DB" uv run python manage.py migrate timesheet 0002 --no-input
# timesheet/0004 clears the Xero pay item from public-holiday time lines, which
# stops those hours being posted on top of the line Xero computes itself. The
# lines it fixes arrive with the restore, so running it against the empty
# database finds nothing; its reverse is a no-op, so replaying it here is the
# same tested code against the rows that now exist.
DB_NAME="$V2_DB" uv run python manage.py migrate timesheet 0003 --no-input
DB_NAME="$V2_DB" uv run python manage.py migrate timesheet 0004 --no-input
# Fable: core was unapplied to 0001 before the restore so v1's phone-provider row
# could land in its own column names. core/0002 now renames those columns and
# adds the Maps key; core/0003 creates the IntegrationSettings row when the
# dump carried none (get_or_create keeps a restored row as-is).
DB_NAME="$V2_DB" uv run python manage.py migrate core 0003 --no-input
# crm/0003 measures every archived recording's length from its file under
# PHONE_RECORDING_STORAGE_ROOT. The rows arrive with the restore above and the
# files with the archive copy (cutover checklist), so the empty-database run
# measured nothing. Its reverse only drops the column, so unapply-reapply is
# the same tested code against the restored rows; a row whose file is absent
# stays NULL and its player shows no length, which is the signal that the
# archive copy was skipped.
DB_NAME="$V2_DB" uv run python manage.py migrate crm 0002 --no-input
DB_NAME="$V2_DB" uv run python manage.py migrate crm 0003 --no-input
# process/0003 derives each document's stored category from its v1 tags. The
# rows it fixes arrive with the restore; its reverse is a no-op, so replaying
# it here is the same tested code against the rows that now exist.
DB_NAME="$V2_DB" uv run python manage.py migrate process 0002 --no-input
DB_NAME="$V2_DB" uv run python manage.py migrate process 0003 --no-input

echo "==> NOTE: formerly-encrypted credential columns"
cat <<'NOTE'
v1 stored Fernet ciphertext in crm_phoneprovidersettings.username/.password and
quoting_suppliercredential.username/.password/.api_key; v2 stores plaintext
(encryption dropped by decision 2026-08-01). Either run the decrypt helper with
v1's FIELD_ENCRYPTION_KEY after this restore, or re-enter the handful of
credentials by hand post-cutover: the phone provider's and the Google Maps key
on Admin > Integrations (they are IntegrationSettings columns now, not .env).
NOTE

echo "==> Resetting sequences"
# `manage.py sync_sequences` (apps/core) implements the same concept for the
# E2E harness. This script keeps its raw-SQL version because it must run
# without a Django environment and is the rehearsed cutover path — unify only
# after cutover.
# pg_get_serial_sequence() resolves BOTH serial-owned and IDENTITY sequences.
# The older idiom (pg_depend WHERE deptype = 'a') finds only serial-owned ones
# and silently matches NOTHING on Django 6, which emits GENERATED BY DEFAULT AS
# IDENTITY (deptype 'i'). That left every sequence at 1 after a load, so the
# first insert into any integer-PK table (simple-history rows, m2m through
# tables) died with a duplicate-key error. Caught by running the app against
# migrated data; see docs/cutover-checklist.md.
# The third setval argument matters: for an empty table pass is_called=false so
# the first value issued is 1, not 2.
psql "$@" -d "$V2_DB" -Atc "
  SELECT format(
           'SELECT setval(%L, COALESCE((SELECT MAX(%I) FROM %I.%I), 1), (SELECT MAX(%I) IS NOT NULL FROM %I.%I));',
           seq, col, sch, tab, col, sch, tab)
  FROM (
    SELECT c.table_schema AS sch, c.table_name AS tab, c.column_name AS col,
           pg_get_serial_sequence(
             quote_ident(c.table_schema) || '.' || quote_ident(c.table_name), c.column_name
           ) AS seq
      FROM information_schema.columns c
     WHERE c.table_schema = 'public'
  ) s
  WHERE seq IS NOT NULL
" | psql "$@" -d "$V2_DB" -q -v ON_ERROR_STOP=1

# Fail loudly if any sequence is still behind its table. The original bug was
# SILENT: the reset "succeeded" while matching zero sequences, and nothing broke
# until the first insert. Verify rather than trust.
MISMATCHES=$(psql "$@" -d "$V2_DB" -Atc "
  SELECT format(
           'SELECT %L WHERE (SELECT last_value FROM %s) < COALESCE((SELECT MAX(%I) FROM %I.%I), 0);',
           tab || '.' || col, seq, col, sch, tab)
  FROM (
    SELECT c.table_schema AS sch, c.table_name AS tab, c.column_name AS col,
           pg_get_serial_sequence(
             quote_ident(c.table_schema) || '.' || quote_ident(c.table_name), c.column_name
           ) AS seq
      FROM information_schema.columns c
     WHERE c.table_schema = 'public'
  ) s
  WHERE seq IS NOT NULL
" | psql "$@" -d "$V2_DB" -Atq)

if [[ -n "$MISMATCHES" ]]; then
  echo "SEQUENCES STILL BEHIND THEIR TABLES:" >&2
  echo "$MISMATCHES" >&2
  exit 1
fi
echo "    every sequence verified at or above its table max"

echo "==> VACUUM ANALYZE"
psql "$@" -d "$V2_DB" -qc "VACUUM ANALYZE"

echo "Done. Now run scripts/ops/db_schema_diff.sh, row-count parity, and the test suites."
