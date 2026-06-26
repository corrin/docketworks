#!/bin/bash
set -euo pipefail

# Usage: legacy_rollback.sh <instance> <oldsha-prefix>
# Example: legacy_rollback.sh msm-uat ea793bd1
#
# Rolls a cutover instance back to its legacy pre-cutover state using the
# snapshot created by cutover_legacy_instance.sh and the paired predeploy
# DB backup. Restores the legacy code tree, database, systemd units, and
# nginx config — then restarts services.
#
# Must run as root. Destructive: drops the current database.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/server/common.sh"
source "$SCRIPT_DIR/server/release-utils.sh"

if [[ $EUID -ne 0 ]]; then
    echo "ERROR: This script must be run as root (use sudo)." >&2
    exit 1
fi

if [[ $# -ne 2 ]]; then
    echo "Usage: $0 <instance> <oldsha-prefix>"
    echo "Example: $0 msm-uat ea793bd1"
    exit 1
fi

INSTANCE="$1"
OLD_PREFIX="$2"
INSTANCE_DIR="$INSTANCES_DIR/$INSTANCE"
ENV_FILE="$INSTANCE_DIR/.env"
BACKUP_DIR="$INSTANCE_DIR/backups"
INST_USER="$(instance_user "$INSTANCE")"

if [[ ! -f "$ENV_FILE" ]]; then
    echo "ERROR: $ENV_FILE missing" >&2
    exit 1
fi

DB_NAME="$(read_env_value "$ENV_FILE" DB_NAME)"
if [[ -z "$DB_NAME" ]]; then
    echo "ERROR: DB_NAME not set in $ENV_FILE" >&2
    exit 1
fi
DB_USER="$(read_env_value "$ENV_FILE" DB_USER)"
if [[ -z "$DB_USER" ]]; then
    echo "ERROR: DB_USER not set in $ENV_FILE" >&2
    exit 1
fi

shopt -s nullglob
SNAPSHOT_MATCHES=("$BACKUP_DIR"/legacy_"$OLD_PREFIX"*.tar.gz)
if (( ${#SNAPSHOT_MATCHES[@]} == 0 )); then
    echo "ERROR: Legacy snapshot not found for prefix $OLD_PREFIX in $BACKUP_DIR" >&2
    echo "Run cutover_legacy_instance.sh first to create one." >&2
    exit 1
elif (( ${#SNAPSHOT_MATCHES[@]} > 1 )); then
    echo "ERROR: Multiple legacy snapshots match prefix $OLD_PREFIX:" >&2
    printf '  %s\n' "${SNAPSHOT_MATCHES[@]}" >&2
    echo "Pass a longer SHA prefix." >&2
    exit 1
fi

SNAPSHOT="${SNAPSHOT_MATCHES[0]}"
OLD_SHORT="$(basename "$SNAPSHOT")"
OLD_SHORT="${OLD_SHORT#legacy_}"
OLD_SHORT="${OLD_SHORT%.tar.gz}"
UNITS_DIR="$BACKUP_DIR/legacy_${OLD_SHORT}.units"
NGINX_BACKUP="$BACKUP_DIR/legacy_${OLD_SHORT}.nginx.conf"

if [[ ! -d "$UNITS_DIR" ]]; then
    echo "ERROR: Legacy unit files not found: $UNITS_DIR" >&2
    exit 1
fi
for unit in gunicorn celery-worker celery-beat; do
    unit_path="$UNITS_DIR/${unit}-${INSTANCE}.service"
    if [[ ! -f "$unit_path" ]]; then
        echo "ERROR: Legacy unit file not found: $unit_path" >&2
        exit 1
    fi
done
if [[ ! -f "$NGINX_BACKUP" ]]; then
    echo "ERROR: Legacy nginx config not found: $NGINX_BACKUP" >&2
    exit 1
fi
if ! tar -tzf "$SNAPSHOT" >/dev/null; then
    echo "ERROR: Legacy snapshot is not a readable gzip tarball: $SNAPSHOT" >&2
    exit 1
fi

# Locate the newest predeploy backup for this legacy SHA.
DB_MATCHES=("$BACKUP_DIR"/predeploy_*_"$OLD_SHORT".sql.gz)
if (( ${#DB_MATCHES[@]} == 0 )); then
    echo "ERROR: No predeploy backup found for hash $OLD_SHORT in $BACKUP_DIR" >&2
    exit 1
fi
mapfile -t SORTED_DB < <(printf '%s\n' "${DB_MATCHES[@]}" | sort)
DB_DUMP="${SORTED_DB[-1]}"

echo "=== Rolling $INSTANCE back to legacy state at $OLD_SHORT ==="
echo "===   Code snapshot:  $SNAPSHOT"
echo "===   DB restore:     $DB_DUMP"
echo "===   Units dir:      $UNITS_DIR"
echo "===   Nginx config:   $NGINX_BACKUP"
echo "=== This will DROP the current database and restore the legacy checkout."
read -rp "Continue? [y/N] " ans
if [[ "$ans" != "y" && "$ans" != "Y" ]]; then
    echo "Aborted."
    exit 1
fi

# --- Stop services ---
log "Stopping services for $INSTANCE"
systemctl stop "celery-beat-$INSTANCE" 2>/dev/null || true
systemctl stop "celery-worker-$INSTANCE" 2>/dev/null || true
systemctl stop "gunicorn-$INSTANCE" 2>/dev/null || true

# --- Drop and recreate the database ---
log "Dropping database $DB_NAME"
sudo -u postgres psql -v ON_ERROR_STOP=1 -v db_name="$DB_NAME" -v db_user="$DB_USER" postgres <<EOSQL
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE datname = :'db_name'
  AND pid <> pg_backend_pid();
DROP DATABASE :"db_name";
CREATE DATABASE :"db_name" OWNER :"db_user";
EOSQL

log "Restoring predeploy backup $DB_DUMP into $DB_NAME"
gunzip -c "$DB_DUMP" | sudo -u postgres psql -v ON_ERROR_STOP=1 "$DB_NAME" >/dev/null
log "Database restore completed"

# --- Restore legacy code tree ---
log "Removing current release link"
rm -f "$INSTANCE_DIR/current" "$INSTANCE_DIR/deploy-state.env"

log "Extracting legacy code tree from $SNAPSHOT"
tar -xzf "$SNAPSHOT" -C "$INSTANCE_DIR"

chown -R "$INST_USER:$INST_USER" "$INSTANCE_DIR"
log "Legacy code tree restored"

# --- Sync database sequences (needs manage.py from restored code) ---
log "Syncing database sequences"
SHARED_VENV=""
for d in "$RELEASES_DIR"/*; do
    [[ -d "$d" && -f "$d/.complete" && -f "$d/.venv/bin/python" ]] || continue
    SHARED_VENV="$d/.venv"
    break
done
if [[ -z "$SHARED_VENV" ]]; then
    echo "ERROR: no shared release venv found for sync_sequences" >&2
    exit 1
fi

sudo -u "$INST_USER" bash -c "
    source '$SHARED_VENV/bin/activate'
    set -a
    source '$INSTANCE_DIR/.env'
    set +a
    export DJANGO_SETTINGS_MODULE=docketworks.settings
    export PYTHONDONTWRITEBYTECODE=1
    cd '$INSTANCE_DIR'
    python manage.py sync_sequences
"
log "Sequence sync complete"

# --- Restore systemd units ---
log "Restoring legacy systemd units"
cp "$UNITS_DIR/gunicorn-$INSTANCE.service" /etc/systemd/system/
cp "$UNITS_DIR/celery-worker-$INSTANCE.service" /etc/systemd/system/
cp "$UNITS_DIR/celery-beat-$INSTANCE.service" /etc/systemd/system/
systemctl daemon-reload

# --- Restore nginx config ---
log "Restoring legacy nginx config"
cp "$NGINX_BACKUP" "/etc/nginx/sites-available/docketworks-$INSTANCE"
if ! nginx -t; then
    echo "ERROR: nginx configuration test failed after restoring legacy config" >&2
    echo "The legacy code tree has been restored but nginx is NOT reloaded." >&2
    exit 1
fi
systemctl reload nginx

# --- Start services ---
if [[ -f "$INSTANCE_DIR/.dr-mode" ]]; then
    log "DR mode (.dr-mode present): leaving services stopped"
else
    log "Starting services for $INSTANCE"
    systemctl start "celery-worker-$INSTANCE"
    systemctl start "celery-beat-$INSTANCE"
    systemctl start "gunicorn-$INSTANCE"
fi

log "=== Legacy rollback complete: $INSTANCE running at $OLD_SHORT ==="
