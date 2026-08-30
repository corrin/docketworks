#!/bin/bash
set -euo pipefail

# TEMPORARY v1->v2 cutover, instance step. Run once per instance, after
# cutover-host.sh. See README.md in this directory; delete the whole
# directory after both hosts are migrated.
#
# Usage: cutover-instance.sh <client> <env> [--ref <ref>]
#
# --ref: the v2 git ref to deploy (default: the instance's tracked ref
# from deploy-state.env — origin/main for UAT, origin/production for
# prod, per ADR 0029).
#
# The instance's services are down from the stop until the final start.
# The v1 database is preserved as <db>_v1_final_<timestamp>; rollback is
# rollback-instance.sh, which needs the state directory this script
# records and prints.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVER_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=../common.sh
source "$SERVER_DIR/common.sh"
# shellcheck source=../release-utils.sh
source "$SERVER_DIR/release-utils.sh"

if [[ $EUID -ne 0 ]]; then
    echo "ERROR: This script must be run as root (use sudo)." >&2
    exit 1
fi

if [[ $# -lt 2 ]]; then
    echo "Usage: $0 <client> <env> [--ref <ref>]" >&2
    exit 1
fi
CLIENT="$1"
ENV="$2"
shift 2
validate_env "$ENV"
INSTANCE="${CLIENT}-${ENV}"
INSTANCE_DIR="$INSTANCES_DIR/$INSTANCE"
INST_USER="$(instance_user "$INSTANCE")"
DB_NAME="dw_${CLIENT}_${ENV}"

REF=""
if ! parsed=$(getopt -o '' --long ref: -n "$(basename "$0")" -- "$@"); then
    echo "Usage: $0 <client> <env> [--ref <ref>]" >&2
    exit 1
fi
eval set -- "$parsed"
while true; do
    case "$1" in
        --ref) REF="$2"; shift 2 ;;
        --) shift; break ;;
    esac
done

# --- Preflight: refuse anything the operator must fix first ---
if [[ ! -f "$INSTANCE_DIR/.env" ]]; then
    echo "ERROR: $INSTANCE_DIR/.env not found — is $INSTANCE a real instance?" >&2
    exit 1
fi
# Already cut over? A v2 release ships uv.lock (v1 shipped poetry.lock);
# re-running would snapshot v2 state as "v1 state" and poison rollback.
if [[ -f "$INSTANCE_DIR/app/uv.lock" ]]; then
    echo "ERROR: $INSTANCE already runs a v2 release — nothing to cut over." >&2
    echo "  Deploy updates with scripts/server/deploy.sh; roll back a cutover" >&2
    echo "  with rollback-instance.sh and the original state directory." >&2
    exit 1
fi
if ! ufw status 2>/dev/null | grep -q '^Status: active'; then
    echo "ERROR: UFW is not active — run cutover-host.sh first." >&2
    exit 1
fi
if [[ "$(git -C "$LOCAL_REPO" remote get-url origin)" != "$REMOTE_REPO_URL" ]]; then
    echo "ERROR: $LOCAL_REPO does not point at the v2 remote — run cutover-host.sh first." >&2
    exit 1
fi
if [[ -z "$REF" ]]; then
    REF="$(read_instance_deploy_ref "$INSTANCE")"
fi
CREDS_FILE="$CONFIG_DIR/$INSTANCE.credentials.env"
require_root_owned_credentials_file "$CREDS_FILE"
GCP_PATH="$(read_env_value "$CREDS_FILE" GCP_CREDENTIALS)"
if [[ -n "$GCP_PATH" && ! -f "$GCP_PATH" ]]; then
    echo "ERROR: GCP_CREDENTIALS in $CREDS_FILE points at a missing file: $GCP_PATH" >&2
    echo "  The instance's live copy still exists; point the variable at it:" >&2
    echo "    GCP_CREDENTIALS=$INSTANCE_DIR/gcp-credentials.json" >&2
    exit 1
fi

STATE_DIR="/opt/docketworks/cutover-state/$INSTANCE-$(date +%Y%m%d_%H%M%S)"
mkdir -p "$STATE_DIR"
chmod 700 "$STATE_DIR"
ln -sfn "$STATE_DIR" "/opt/docketworks/cutover-state/$INSTANCE-latest"

log "=========================================="
log "v1->v2 cutover for $INSTANCE; state recorded in $STATE_DIR"
log "=========================================="

# --- Record the complete v1 state rollback-instance.sh restores ---
PREVIOUS_SHA="$(instance_current_sha "$INSTANCE")"
if [[ -z "$PREVIOUS_SHA" ]]; then
    echo "ERROR: $INSTANCE has no current release link." >&2
    exit 1
fi
cp -p "$INSTANCE_DIR/.env" "$STATE_DIR/env"
cp -p "$INSTANCE_DIR/deploy-state.env" "$STATE_DIR/deploy-state.env" 2>/dev/null || true
for unit in "gunicorn-$INSTANCE" "celery-beat-$INSTANCE" "celery-worker-$INSTANCE"; do
    cp -p "/etc/systemd/system/$unit.service" "$STATE_DIR/" 2>/dev/null || true
done
cp -p "/etc/nginx/sites-available/docketworks-$INSTANCE" "$STATE_DIR/nginx.conf"
# A .dr-mode WITH the .dr-mode.cutover marker is this script's own
# hold-down left by a previous failed attempt, not a genuine DR posture —
# recording it as HAD_DR_MODE=true would make the retry finish with
# services permanently down.
HAD_DR_MODE=false
if [[ -f "$INSTANCE_DIR/.dr-mode" && ! -f "$INSTANCE_DIR/.dr-mode.cutover" ]]; then
    HAD_DR_MODE=true
fi
{
    echo "INSTANCE=$INSTANCE"
    echo "DB_NAME=$DB_NAME"
    echo "PREVIOUS_SHA=$PREVIOUS_SHA"
    echo "HAD_DR_MODE=$HAD_DR_MODE"
} > "$STATE_DIR/manifest.env"

# v1 hosts' company-defaults config predates CompanyDefaults' move to
# apps/core; v2's validator (correctly) refuses the old model label, so
# rewrite it in place (original preserved in $STATE_DIR) before
# reconfigure runs. The file is a fresh-create bootstrap source —
# reconfigure only validates it, never loads it.
COMPANY_DEFAULTS_FILE="$CONFIG_DIR/$INSTANCE.company-defaults.json"
if [[ -f "$COMPANY_DEFAULTS_FILE" ]] && grep -q '"workflow\.companydefaults"' "$COMPANY_DEFAULTS_FILE"; then
    log "Rewriting v1 model label in $COMPANY_DEFAULTS_FILE (workflow.companydefaults -> core.companydefaults)"
    cp -p "$COMPANY_DEFAULTS_FILE" "$STATE_DIR/company-defaults.v1.json"
    rewrite_v1_company_defaults_labels "$COMPANY_DEFAULTS_FILE"
fi

# --- Prove the reconfigure below will pass, while v1 is still up ---
# Fable: relying on reconfigure's own validation is rejected — it runs
# after the service stop, the final backup and the release flip, so a v1
# credentials file missing a v2-only key (BACKUP_GDRIVE_TEAM_DRIVE_ID on
# the first live run) strands the instance down on v2 config with the
# data not yet migrated. Same checks, nothing changed yet; sits after the
# label rewrite above because the validator requires the v2 model label.
"$SERVER_DIR/instance.sh" validate-config "$CLIENT" "$ENV"

# --- Stop v1 and take the verified final v1 backup ---
stop_instance_services_strict "$INSTANCE"
# The backup timers stay down for the whole migration: a nightly pg_dump
# firing mid-flow would be killed by the database swap's
# pg_terminate_backend — or worse, overwrite the last v1 daily dump with
# v2 contents. Re-enabled at go-live below.
systemctl stop "backup-db-$INSTANCE.timer" 2>/dev/null || true
systemctl stop "backup-files-$INSTANCE.timer" 2>/dev/null || true

FINAL_BACKUP="$STATE_DIR/pre-cutover_${DB_NAME}.sql.gz"
log "Taking final v1 backup of $DB_NAME..."
sudo -u postgres pg_dump "$DB_NAME" | gzip > "$FINAL_BACKUP"
gunzip -t "$FINAL_BACKUP"
if [[ "$(stat -c '%s' "$FINAL_BACKUP")" -lt 10240 ]]; then
    echo "ERROR: final backup is implausibly small ($(stat -c '%s' "$FINAL_BACKUP") bytes); aborting." >&2
    exit 1
fi
log "  Final v1 backup verified: $FINAL_BACKUP"

# --- Build the v2 release and point the instance at it ---
fetch_local_repo
TARGET_SHA="$(resolve_release_ref "$REF")"
log "Resolved $REF to $TARGET_SHA"
ensure_release "$TARGET_SHA"
switch_instance_release "$INSTANCE" "$TARGET_SHA"
chown -h "$INST_USER:$INST_USER" "$INSTANCE_DIR/app"

# --- Reconfigure onto the v2 contract, services still stopped ---
# reconfigure renders the v2 .env (DB password and SECRET_KEY preserved;
# JWT_SIGNING_KEY and the per-instance Redis database generated fresh —
# the fresh signing key is the deliberate one-time re-login), installs
# the v2 systemd units, nginx config and sudoers, and would normally
# restart services — .dr-mode holds them down until the database swap
# below, because v2 code against the not-yet-migrated v1 schema serves
# only errors.
# --skip-db-fixtures: the database is still v1 schema here, and the
# credential-derived rows touch v2-only columns (the Maps key lives in
# crm_phoneprovidersettings.google_maps_api_key) — loaded after the swap
# below. Fable: moving the whole reconfigure past the swap was rejected:
# the migration stages source the v2 .env this reconfigure renders.
touch "$INSTANCE_DIR/.dr-mode"
if [[ "$HAD_DR_MODE" == "false" ]]; then
    # Marks the .dr-mode as this script's own hold-down, so a retry after
    # a mid-flow failure does not mistake it for a genuine DR posture.
    touch "$INSTANCE_DIR/.dr-mode.cutover"
fi
"$SERVER_DIR/instance.sh" reconfigure "$CLIENT" "$ENV" --skip-db-fixtures
# reconfigure enable --now'd the backup timers; hold them down again
# until the database swap is done.
systemctl stop "backup-db-$INSTANCE.timer" 2>/dev/null || true
systemctl stop "backup-files-$INSTANCE.timer" 2>/dev/null || true

# --- Migrate the data: fresh v2 schema, v1 data, rename swap ---
SCRATCH_DB="${DB_NAME}_v2new_$$"
V1_FINAL_DB="${DB_NAME}_v1_final_$(date +%Y%m%d_%H%M%S)"
echo "V1_FINAL_DB=$V1_FINAL_DB" >> "$STATE_DIR/manifest.env"

log "Creating $SCRATCH_DB and applying v2 migrations..."
sudo -u postgres createdb --owner "$INST_USER" "$SCRATCH_DB"
run_release_command "$INSTANCE" "$TARGET_SHA" "$SCRATCH_DB" \
    python manage.py migrate --no-input

log "Migrating v1 data $DB_NAME -> $SCRATCH_DB (rehearsed flow)..."
# As the instance user, not postgres: the script ends with Django
# management commands (uv run manage.py migrate quoting ...), which need
# the release working directory, the instance env contract and uv on
# PATH — none of which the postgres user has. The pg-tool stages work as
# the instance user too: it owns both databases, and PGPASSWORD carries
# the scram credential the socket requires. UV_NO_SYNC keeps uv from
# trying to write into the docketworks-owned release venv.
RELEASE_DIR="$(release_path "$TARGET_SHA")"
sudo -u "$INST_USER" bash -c "
    set -euo pipefail
    set -a
    source '$INSTANCE_DIR/.env'
    set +a
    export PGPASSWORD=\"\$DB_PASSWORD\"
    export PATH='/opt/docketworks/.local/bin:$RELEASE_DIR/.venv/bin:/usr/local/bin:/usr/bin:/bin'
    export UV_NO_SYNC=1
    cd '$RELEASE_DIR'
    bash scripts/ops/migrate_v1_data.sh '$DB_NAME' '$SCRATCH_DB'
"

log "Validating restored data against v2 model contracts..."
run_release_command "$INSTANCE" "$TARGET_SHA" "$SCRATCH_DB" \
    python -m scripts.ops.validate_restored_data
run_release_command "$INSTANCE" "$TARGET_SHA" "$SCRATCH_DB" \
    python manage.py migrate --check
run_release_command "$INSTANCE" "$TARGET_SHA" "$SCRATCH_DB" \
    python manage.py check

log "Swapping databases: $DB_NAME -> $V1_FINAL_DB; $SCRATCH_DB -> $DB_NAME"
sudo -u postgres psql \
    -v ON_ERROR_STOP=1 \
    -v db_name="$DB_NAME" \
    -v scratch_db="$SCRATCH_DB" \
    -v v1_final_db="$V1_FINAL_DB" \
    postgres <<'EOSQL'
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE datname IN (:'db_name', :'scratch_db')
  AND pid <> pg_backend_pid();
SELECT format('ALTER DATABASE %I RENAME TO %I', :'db_name', :'v1_final_db') \gexec
SELECT format('ALTER DATABASE %I RENAME TO %I', :'scratch_db', :'db_name') \gexec
EOSQL

# --- Restore v1's formerly-encrypted credentials, if extracted ---
# Fable: extract_v1_credentials.py decrypts the five Fernet columns to a file
# in phase 0, while v1 is intact and its key readable. Applying it HERE — on
# the live database, after the swap and BEFORE load-db-fixtures — is what
# lets the fixture loader see a configured phone group and honour it rather
# than the migration's cleared placeholders. Absent file = a scrubbed or
# key-less restore; migrate_v1_data.sh's clearing stands and the operator
# re-enters by hand.
CREDENTIALS_FILE="$STATE_DIR/v1-credentials.json"
if [[ -f "$CREDENTIALS_FILE" ]]; then
    log "Applying extracted v1 credentials from $CREDENTIALS_FILE..."
    install -o "$INST_USER" -g "$INST_USER" -m 600 "$CREDENTIALS_FILE" \
        "$INSTANCE_DIR/v1-credentials.json"
    run_release_command "$INSTANCE" "$TARGET_SHA" "$DB_NAME" \
        python scripts/ops/apply_v1_credentials.py "$INSTANCE_DIR/v1-credentials.json"
    rm -f "$INSTANCE_DIR/v1-credentials.json"
else
    log "No extracted v1 credentials at $CREDENTIALS_FILE; using cleared columns (re-enter by hand)."
fi

# --- Load the credential-derived DB rows, now the schema is v2 ---
# Deferred from reconfigure above (--skip-db-fixtures). Before go-live so
# the app never serves without the integration settings; idempotent, so a
# retry that finds rows already present (or migrated from v1) skips them.
"$SERVER_DIR/instance.sh" load-db-fixtures "$CLIENT" "$ENV"

# --- Go live ---
# Backup timers come back in both postures: DR standbys back up too (they
# were only held down for the migration window).
systemctl enable --now "backup-db-$INSTANCE.timer"
systemctl enable --now "backup-files-$INSTANCE.timer"
if [[ "$HAD_DR_MODE" == "true" ]]; then
    log "Instance was in DR mode before cutover; leaving .dr-mode in place (services stay down)."
else
    rm -f "$INSTANCE_DIR/.dr-mode" "$INSTANCE_DIR/.dr-mode.cutover"
    for unit in "celery-worker-$INSTANCE" "celery-beat-$INSTANCE" "gunicorn-$INSTANCE"; do
        systemctl enable "$unit"
        systemctl restart "$unit"
    done
fi

write_deploy_state \
    "$INSTANCE" "$PREVIOUS_SHA" "$TARGET_SHA" "$INST_USER" "$REF" "cutover-v2"

log "Running verification..."
if [[ "$HAD_DR_MODE" == "true" ]]; then
    log "  Skipping verify-instance.sh (DR mode: services deliberately down)."
    # Fable: the service checks are meaningless on a standby, but the
    # DB-backed integration probe needs only the venv and the swapped
    # database, both up — without it a bad Maps key or a dropped phone group
    # on a DR host surfaces only at failover, on the newly promoted primary.
    log "  Probing DB-backed integrations (valid on a standby)..."
    "$SERVER_DIR/dw-run.sh" "$INSTANCE" \
        python -m scripts.ops.restore_checks.check_integration_settings
else
    "$SERVER_DIR/verify-instance.sh" "$CLIENT" "$ENV"
fi

log "=========================================="
log "$INSTANCE now runs v2 release $(short_release_sha "$TARGET_SHA")"
log "  v1 database preserved as: $V1_FINAL_DB"
log "  Rollback (if needed): sudo $SCRIPT_DIR/rollback-instance.sh $CLIENT $ENV"
log "  State: $STATE_DIR"
log "=========================================="
