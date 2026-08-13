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
HAD_DR_MODE=false
[[ -f "$INSTANCE_DIR/.dr-mode" ]] && HAD_DR_MODE=true
{
    echo "INSTANCE=$INSTANCE"
    echo "DB_NAME=$DB_NAME"
    echo "PREVIOUS_SHA=$PREVIOUS_SHA"
    echo "HAD_DR_MODE=$HAD_DR_MODE"
} > "$STATE_DIR/manifest.env"

# --- Stop v1 and take the verified final v1 backup ---
stop_instance_services_strict "$INSTANCE"

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
touch "$INSTANCE_DIR/.dr-mode"
"$SERVER_DIR/instance.sh" reconfigure "$CLIENT" "$ENV"

# --- Migrate the data: fresh v2 schema, v1 data, rename swap ---
SCRATCH_DB="${DB_NAME}_v2new_$$"
V1_FINAL_DB="${DB_NAME}_v1_final_$(date +%Y%m%d_%H%M%S)"
echo "V1_FINAL_DB=$V1_FINAL_DB" >> "$STATE_DIR/manifest.env"

log "Creating $SCRATCH_DB and applying v2 migrations..."
sudo -u postgres createdb --owner "$INST_USER" "$SCRATCH_DB"
run_release_command "$INSTANCE" "$TARGET_SHA" "$SCRATCH_DB" \
    python manage.py migrate --no-input

log "Migrating v1 data $DB_NAME -> $SCRATCH_DB (rehearsed flow)..."
RELEASE_DIR="$(release_path "$TARGET_SHA")"
sudo -u postgres bash "$RELEASE_DIR/scripts/ops/migrate_v1_data.sh" "$DB_NAME" "$SCRATCH_DB"

log "Validating restored data against v2 model contracts..."
run_release_command "$INSTANCE" "$TARGET_SHA" "$SCRATCH_DB" \
    python scripts/ops/validate_restored_data.py
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

# --- Go live ---
if [[ "$HAD_DR_MODE" == "true" ]]; then
    log "Instance was in DR mode before cutover; leaving .dr-mode in place (services stay down)."
else
    rm -f "$INSTANCE_DIR/.dr-mode"
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
else
    "$SCRIPT_DIR/verify-instance.sh" "$CLIENT" "$ENV"
fi

log "=========================================="
log "$INSTANCE now runs v2 release $(short_release_sha "$TARGET_SHA")"
log "  v1 database preserved as: $V1_FINAL_DB"
log "  Rollback (if needed): sudo $SCRIPT_DIR/rollback-instance.sh $CLIENT $ENV"
log "  State: $STATE_DIR"
log "=========================================="
