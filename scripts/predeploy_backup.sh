#!/bin/bash
set -euo pipefail

# Usage: predeploy_backup.sh <instance>
# Example: predeploy_backup.sh msm-prod
#
# Captures the instance's current HEAD short hash + a timestamp, then
# pg_dumps the instance DB into:
#   /opt/docketworks/instances/<instance>/backups/predeploy_<ts>_<hash>.sql.gz
#
# The hash tags the dump with the commit that produced the data, so a
# rollback pair is (`git checkout <hash>`, restore this file).
#
# Must run as root (calls `sudo -u postgres pg_dump`).

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/server/common.sh"

if [[ $# -lt 1 ]]; then
    echo "Usage: $0 <instance>"
    echo "Example: $0 msm-prod"
    exit 1
fi

INSTANCE="$1"
INSTANCE_DIR="$INSTANCES_DIR/$INSTANCE"
ENV_FILE="$INSTANCE_DIR/.env"
BACKUP_DIR="$INSTANCE_DIR/backups"

if [[ ! -f "$ENV_FILE" ]]; then
    echo "ERROR: $ENV_FILE missing" >&2
    exit 1
fi
if [[ ! -d "$INSTANCE_DIR/.git" ]]; then
    echo "ERROR: $INSTANCE_DIR is not a git checkout" >&2
    exit 1
fi

DB_NAME=$(grep -E '^DB_NAME=' "$ENV_FILE" | cut -d= -f2)
if [[ -z "$DB_NAME" ]]; then
    echo "ERROR: DB_NAME not set in $ENV_FILE" >&2
    exit 1
fi

INST_USER="$(instance_user "$INSTANCE")"
HASH=$(sudo -u "$INST_USER" git -C "$INSTANCE_DIR" rev-parse --short HEAD)
TS=$(date +%Y%m%d_%H%M%S)
OUT="$BACKUP_DIR/predeploy_${TS}_${HASH}.sql.gz"

mkdir -p "$BACKUP_DIR"

# Atomic write: dump to .tmp, rename on success. A mid-dump failure then
# leaves a .tmp file (not a finished-looking predeploy_*.sql.gz).
# pipefail ensures pg_dump failure fails the pipeline even though gzip
# would succeed on empty input.
sudo -u postgres pg_dump "$DB_NAME" | gzip > "$OUT.tmp"
mv "$OUT.tmp" "$OUT"

echo "Wrote $OUT"
