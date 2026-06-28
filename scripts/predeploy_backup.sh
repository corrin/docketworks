#!/bin/bash
set -euo pipefail

# Usage: predeploy_backup.sh <instance>
# Example: predeploy_backup.sh msm-prod
#
# Captures the instance's current release short hash + a timestamp, then
# pg_dumps the instance DB into:
#   /opt/docketworks/instances/<instance>/backups/predeploy_<ts>_<hash>.sql.gz
#
# The hash tags the dump with the commit that produced the data, so a
# rollback pair is (switch app to <hash>, restore this file).
#
# Must run as root (calls `sudo -u postgres pg_dump`).

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/server/common.sh"
source "$SCRIPT_DIR/server/release-utils.sh"

if [[ $# -lt 1 ]]; then
    echo "Usage: $0 <instance>"
    echo "Example: $0 msm-prod"
    exit 1
fi

INSTANCE="$1"
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

HASH="$(instance_current_sha "$INSTANCE")"
if [[ -z "$HASH" ]]; then
    echo "ERROR: could not determine current release SHA for $INSTANCE" >&2
    exit 1
fi
HASH="$(short_release_sha "$HASH")"
TS=$(date +%Y%m%d_%H%M%S)

ensure_instance_backup_dir "$INSTANCE" "$INST_USER"
OUT="$BACKUP_DIR/predeploy_${TS}_${HASH}.sql.gz"

# Atomic write: dump to .tmp, rename on success. A mid-dump failure then
# leaves a .tmp file (not a finished-looking predeploy_*.sql.gz).
# pipefail ensures pg_dump failure fails the pipeline even though gzip
# would succeed on empty input.
sudo -u postgres pg_dump "$DB_NAME" | gzip > "$OUT.tmp"
mv "$OUT.tmp" "$OUT"

echo "Wrote $OUT"
