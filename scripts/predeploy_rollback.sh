#!/bin/bash
set -euo pipefail

# Usage: predeploy_rollback.sh <instance> <8-char-hash>
# Example: predeploy_rollback.sh msm-prod b54eddc7
#
# Rolls an instance back to a specific release and its paired pre-deploy
# DB backup. Locates the newest predeploy_*_<8-char-hash>*.sql.gz in the
# instance's backups dir, prompts for confirmation, restores the dump into a
# temporary DB, stops services, swaps the DB and release, and restarts services.
#
# Must run as root. Destructive: drops the current DB contents.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/server/common.sh"
source "$SCRIPT_DIR/server/release-utils.sh"

if [[ $EUID -ne 0 ]]; then
    echo "ERROR: This script must be run as root (use sudo)." >&2
    exit 1
fi

if [[ $# -ne 2 ]]; then
    echo "Usage: $0 <instance> <8-char-hash>"
    echo "Example: $0 msm-prod b54eddc7"
    exit 1
fi

INSTANCE="$1"
HASH="$2"
INSTANCE_DIR="$INSTANCES_DIR/$INSTANCE"
ENV_FILE="$INSTANCE_DIR/.env"
BACKUP_DIR="$INSTANCE_DIR/backups"
INST_USER="$(instance_user "$INSTANCE")"
SERVICE="gunicorn-$INSTANCE"

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

if ! BACKUP="$(newest_predeploy_backup_for_sha "$BACKUP_DIR" "$HASH")"; then
    echo "ERROR: no predeploy backup found for hash $HASH in $BACKUP_DIR" >&2
    exit 1
fi

FULL_SHA="$(resolve_existing_release_sha "$HASH")"
if ! release_complete "$FULL_SHA"; then
    echo "ERROR: release $FULL_SHA is not present under $RELEASES_DIR" >&2
    echo "Deploy or rebuild that release before rollback." >&2
    exit 1
fi
PRE_ROLLBACK_SHA="$(instance_current_sha "$INSTANCE")"

echo "=== Rolling $INSTANCE back to $HASH using:"
echo "===   $BACKUP"
echo "=== This will restore the backup, stop services, swap DBs, switch app to $FULL_SHA, and restart services."
read -rp "Continue? [y/N] " ans
if [[ "$ans" != "y" && "$ans" != "Y" ]]; then
    echo "Aborted."
    exit 1
fi

RESTORE_DB="${DB_NAME}_rollback_restore_$(date +%Y%m%d_%H%M%S)_$$"
OLD_DB="${DB_NAME}_rollback_old_$(date +%Y%m%d_%H%M%S)_$$"
CLEANUP_RESTORE_DB=1

cleanup_restore_db() {
    if [[ "${CLEANUP_RESTORE_DB:-0}" -eq 1 ]]; then
        sudo -u postgres dropdb --if-exists "$RESTORE_DB" 2>/dev/null || true
    fi
}
trap cleanup_restore_db EXIT

echo "=== Restoring $BACKUP into temporary DB $RESTORE_DB"
sudo -u postgres createdb --owner "$DB_USER" "$RESTORE_DB"
gunzip -c "$BACKUP" | sudo -u postgres psql -v ON_ERROR_STOP=1 "$RESTORE_DB" >/dev/null
echo "=== Temporary DB restore completed"

echo "=== Stopping services"
systemctl stop "celery-beat-$INSTANCE" 2>/dev/null || true
systemctl stop "celery-worker-$INSTANCE" 2>/dev/null || true
systemctl stop "$SERVICE" 2>/dev/null || true

echo "=== Swapping restored DB into place"
sudo -u postgres psql \
    -v ON_ERROR_STOP=1 \
    -v db_name="$DB_NAME" \
    -v restore_db="$RESTORE_DB" \
    -v old_db="$OLD_DB" \
    postgres <<'EOSQL'
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE datname IN (:'db_name', :'restore_db')
  AND pid <> pg_backend_pid();
SELECT format('ALTER DATABASE %I RENAME TO %I', :'db_name', :'old_db') \gexec
SELECT format('ALTER DATABASE %I RENAME TO %I', :'restore_db', :'db_name') \gexec
EOSQL
CLEANUP_RESTORE_DB=0

echo "=== Switching app release to $FULL_SHA"
switch_instance_release "$INSTANCE" "$FULL_SHA"
chown -h "$INST_USER:$INST_USER" "$INSTANCE_DIR/app"
write_deploy_state "$INSTANCE" "$PRE_ROLLBACK_SHA" "$FULL_SHA" "$INST_USER"

echo "=== Dropping replaced DB $OLD_DB"
sudo -u postgres dropdb --if-exists "$OLD_DB"

echo "=== Starting services"
if [[ -f "$INSTANCE_DIR/.dr-mode" ]]; then
    echo "=== DR mode present; leaving services stopped."
else
    systemctl start "celery-worker-$INSTANCE"
    systemctl start "celery-beat-$INSTANCE"
    systemctl start "$SERVICE"
fi

echo "=== Rollback complete."
