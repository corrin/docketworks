#!/bin/bash
set -euo pipefail

# Usage: predeploy_rollback.sh <instance> <hash>
# Example: predeploy_rollback.sh msm-prod b54eddc7
#
# Rolls an instance back to a specific commit and its paired pre-deploy
# DB backup. Locates the newest predeploy_*_<hash>.sql.gz in the
# instance's backups dir, prompts for confirmation, stops gunicorn,
# checks out the commit, restores the DB, and restarts gunicorn.
#
# Must run as root. Destructive: drops the current DB contents.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/server/common.sh"

if [[ $# -ne 2 ]]; then
    echo "Usage: $0 <instance> <hash>"
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

DB_NAME=$(grep -E '^DB_NAME=' "$ENV_FILE" | cut -d= -f2)
if [[ -z "$DB_NAME" ]]; then
    echo "ERROR: DB_NAME not set in $ENV_FILE" >&2
    exit 1
fi

shopt -s nullglob
MATCHES=("$BACKUP_DIR"/predeploy_*_"$HASH".sql.gz)
if (( ${#MATCHES[@]} == 0 )); then
    echo "ERROR: no predeploy backup found for hash $HASH in $BACKUP_DIR" >&2
    exit 1
fi

# Filenames contain YYYYMMDD_HHMMSS so lexicographic sort == chronological;
# last element is newest.
IFS=$'\n' SORTED=($(printf '%s\n' "${MATCHES[@]}" | sort))
unset IFS
BACKUP="${SORTED[-1]}"

echo "=== Rolling $INSTANCE back to $HASH using:"
echo "===   $BACKUP"
echo "=== This will stop $SERVICE, check out $HASH, and restore the DB."
read -rp "Continue? [y/N] " ans
if [[ "$ans" != "y" && "$ans" != "Y" ]]; then
    echo "Aborted."
    exit 1
fi

echo "=== Stopping $SERVICE"
systemctl stop "$SERVICE"

echo "=== Checking out $HASH in $INSTANCE_DIR"
sudo -u "$INST_USER" git -C "$INSTANCE_DIR" checkout "$HASH"

echo "=== Restoring DB $DB_NAME from $BACKUP"
gunzip -c "$BACKUP" | sudo -u postgres psql "$DB_NAME"

echo "=== Starting $SERVICE"
systemctl start "$SERVICE"

echo "=== Rollback complete."
echo "=== Note: frontend dist and shared Python/node deps were NOT rebuilt."
echo "=== If the old commit's deps or frontend diverge from current shared state, run:"
echo "===   sudo $SCRIPT_DIR/server/dw-run.sh $INSTANCE bash -c 'cd frontend && npm run build'"
echo "=== and/or re-run poetry install from $LOCAL_REPO."
