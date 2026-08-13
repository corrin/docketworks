#!/bin/bash
set -euo pipefail

# TEMPORARY v1->v2 cutover rollback, instance step. Restores the v1 state
# recorded by cutover-instance.sh: unit files, nginx config, .env, release
# link and database. See README.md in this directory.
#
# Usage: rollback-instance.sh <client> <env> [--state <state-dir>]
#
# --state: which recorded snapshot to restore (default: the
# <instance>-latest symlink cutover-instance.sh maintains).

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
    echo "Usage: $0 <client> <env> [--state <state-dir>]" >&2
    exit 1
fi
CLIENT="$1"
ENV="$2"
shift 2
validate_env "$ENV"
INSTANCE="${CLIENT}-${ENV}"
INSTANCE_DIR="$INSTANCES_DIR/$INSTANCE"
INST_USER="$(instance_user "$INSTANCE")"

STATE_DIR="/opt/docketworks/cutover-state/$INSTANCE-latest"
if ! parsed=$(getopt -o '' --long state: -n "$(basename "$0")" -- "$@"); then
    echo "Usage: $0 <client> <env> [--state <state-dir>]" >&2
    exit 1
fi
eval set -- "$parsed"
while true; do
    case "$1" in
        --state) STATE_DIR="$2"; shift 2 ;;
        --) shift; break ;;
    esac
done

if [[ ! -f "$STATE_DIR/manifest.env" ]]; then
    echo "ERROR: No cutover state at $STATE_DIR (manifest.env missing)." >&2
    exit 1
fi
DB_NAME="$(read_env_value "$STATE_DIR/manifest.env" DB_NAME)"
PREVIOUS_SHA="$(read_env_value "$STATE_DIR/manifest.env" PREVIOUS_SHA)"
V1_FINAL_DB="$(read_env_value "$STATE_DIR/manifest.env" V1_FINAL_DB)"
HAD_DR_MODE="$(read_env_value "$STATE_DIR/manifest.env" HAD_DR_MODE)"
if [[ -z "$DB_NAME" || -z "$PREVIOUS_SHA" ]]; then
    echo "ERROR: $STATE_DIR/manifest.env is incomplete." >&2
    exit 1
fi
if ! release_complete "$PREVIOUS_SHA"; then
    echo "ERROR: recorded v1 release $PREVIOUS_SHA is no longer on disk." >&2
    echo "  Restore from the recorded backup by hand: $STATE_DIR" >&2
    exit 1
fi

echo "Rolling $INSTANCE back to v1 state recorded in $STATE_DIR"
echo "  v1 release:  $(short_release_sha "$PREVIOUS_SHA")"
echo "  v1 database: ${V1_FINAL_DB:-'(none recorded — cutover stopped before the DB swap)'}"
read -r -p "Continue? (yes/no): " CONFIRM
if [[ "$CONFIRM" != "yes" ]]; then
    echo "Aborted."
    exit 0
fi

log "Stopping v2 services for $INSTANCE..."
for unit in "celery-beat-$INSTANCE" "celery-worker-$INSTANCE" "gunicorn-$INSTANCE"; do
    systemctl stop "$unit" 2>/dev/null || true
done

# --- Database: put v1 back if the cutover got as far as the swap ---
if [[ -n "$V1_FINAL_DB" ]] && \
    sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname = '$V1_FINAL_DB'" | grep -q 1; then
    V2_ASIDE_DB="${DB_NAME}_v2_rolledback_$(date +%Y%m%d_%H%M%S)"
    log "Renaming $DB_NAME -> $V2_ASIDE_DB; $V1_FINAL_DB -> $DB_NAME"
    sudo -u postgres psql \
        -v ON_ERROR_STOP=1 \
        -v db_name="$DB_NAME" \
        -v v2_aside_db="$V2_ASIDE_DB" \
        -v v1_final_db="$V1_FINAL_DB" \
        postgres <<'EOSQL'
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE datname IN (:'db_name', :'v1_final_db')
  AND pid <> pg_backend_pid();
SELECT format('ALTER DATABASE %I RENAME TO %I', :'db_name', :'v2_aside_db') \gexec
SELECT format('ALTER DATABASE %I RENAME TO %I', :'v1_final_db', :'db_name') \gexec
EOSQL
else
    log "No v1_final database recorded/found — cutover stopped before the swap; $DB_NAME is untouched v1 data."
fi

# --- Files: .env, units, nginx, release link ---
log "Restoring recorded v1 .env, unit files and nginx config..."
if [[ -f "$STATE_DIR/company-defaults.v1.json" ]]; then
    install -m 600 -o root -g root "$STATE_DIR/company-defaults.v1.json" \
        "$CONFIG_DIR/$INSTANCE.company-defaults.json"
fi
install -m 600 -o "$INST_USER" -g "$INST_USER" "$STATE_DIR/env" "$INSTANCE_DIR/.env"
if [[ -f "$STATE_DIR/deploy-state.env" ]]; then
    install -m 600 -o "$INST_USER" -g "$INST_USER" \
        "$STATE_DIR/deploy-state.env" "$INSTANCE_DIR/deploy-state.env"
fi
for unit in "gunicorn-$INSTANCE" "celery-beat-$INSTANCE" "celery-worker-$INSTANCE"; do
    if [[ -f "$STATE_DIR/$unit.service" ]]; then
        cp -p "$STATE_DIR/$unit.service" "/etc/systemd/system/$unit.service"
    fi
done
systemctl daemon-reload
cp -p "$STATE_DIR/nginx.conf" "/etc/nginx/sites-available/docketworks-$INSTANCE"
nginx -t && systemctl reload nginx

switch_instance_release "$INSTANCE" "$PREVIOUS_SHA"
chown -h "$INST_USER:$INST_USER" "$INSTANCE_DIR/app"

systemctl enable --now "backup-db-$INSTANCE.timer"
systemctl enable --now "backup-files-$INSTANCE.timer"
if [[ "$HAD_DR_MODE" == "true" ]]; then
    touch "$INSTANCE_DIR/.dr-mode"
    rm -f "$INSTANCE_DIR/.dr-mode.cutover"
    log "Instance was DR before cutover; .dr-mode restored, services stay down."
else
    rm -f "$INSTANCE_DIR/.dr-mode" "$INSTANCE_DIR/.dr-mode.cutover"
    for unit in "celery-worker-$INSTANCE" "celery-beat-$INSTANCE" "gunicorn-$INSTANCE"; do
        systemctl enable "$unit"
        systemctl restart "$unit"
    done
fi

log "$INSTANCE rolled back to v1 release $(short_release_sha "$PREVIOUS_SHA")."
