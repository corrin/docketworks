#!/usr/bin/env bash
# One-time v1 -> v2 data migration (plan §Data migration).
#
# Usage: scripts/migrate_v1_data.sh <v1_db> <v2_db> [psql-connection-args...]
#
# Preconditions: <v2_db> exists and has been freshly `manage.py migrate`d
# (empty of data beyond migration bookkeeping). Both DBs share table names by
# construction (app labels unchanged; moved models pin db_table).
#
# Steps: data-only dump of v1 (excluding infrastructure tables that v2 owns) ->
# restore with triggers disabled (sidesteps FK ordering) -> remap contenttypes
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
-- dump); rows referencing them by FK were restored with triggers disabled, so
-- remap any stale references here if a table carries content_type_id. As of
-- Phase 2 no ported table does; extend this block if one appears.
SQL

echo "==> NOTE: formerly-encrypted credential columns"
cat <<'NOTE'
v1 stored Fernet ciphertext in crm_phoneprovidersettings.username/.password and
quoting_suppliercredential.username/.password/.api_key; v2 stores plaintext
(encryption dropped by decision 2026-08-01). Either run the decrypt helper with
v1's FIELD_ENCRYPTION_KEY after this restore, or re-enter the handful of
credentials by hand post-cutover.
NOTE

echo "==> Resetting sequences"
psql "$@" -d "$V2_DB" -Atc "
  SELECT 'SELECT setval(' || quote_literal(quote_ident(s.relname)) ||
         ', COALESCE((SELECT MAX(' || quote_ident(a.attname) || ') FROM ' ||
         quote_ident(t.relname) || '), 1));'
  FROM pg_class s
  JOIN pg_depend d ON d.objid = s.oid AND d.deptype = 'a'
  JOIN pg_class t ON t.oid = d.refobjid
  JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = d.refobjsubid
  WHERE s.relkind = 'S'
" | psql "$@" -d "$V2_DB" -q

echo "==> VACUUM ANALYZE"
psql "$@" -d "$V2_DB" -qc "VACUUM ANALYZE"

echo "Done. Now run scripts/db_schema_diff.sh, row-count parity, and the test suites."
