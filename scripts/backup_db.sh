#!/bin/bash
set -euo pipefail

# Usage: backup_db.sh <instance>
# Example: backup_db.sh <client>-<env>

if [[ $# -lt 1 ]]; then
    echo "Usage: $0 <instance>"
    echo "Example: $0 <client>-<env>"
    exit 1
fi

INSTANCE="$1"
INSTANCE_DIR="/opt/docketworks/instances/$INSTANCE"
BACKUP_DIR="$INSTANCE_DIR/backups"
ENV_FILE="$INSTANCE_DIR/.env"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SCRIPT_PATH="$SCRIPT_DIR/$(basename "$0")"
EXPECTED_USER="dw_${INSTANCE//-/_}"

if [[ $EUID -eq 0 ]]; then
    exec sudo -u "$EXPECTED_USER" "$SCRIPT_PATH" "$@"
fi

if [[ "$(id -un)" != "$EXPECTED_USER" ]]; then
    echo "Error: backup for $INSTANCE must run as $EXPECTED_USER" >&2
    exit 1
fi

if [[ ! -f "$ENV_FILE" ]]; then
    echo "Error: .env not found at $ENV_FILE" >&2
    exit 1
fi

# Read DB settings from instance .env.
set -a
# shellcheck source=/dev/null  # runtime .env path, not statically resolvable
source "$ENV_FILE"
set +a
for var in DB_NAME DB_USER DB_PASSWORD; do
    if [[ -z "${!var:-}" ]]; then
        echo "Error: $var not set in $ENV_FILE" >&2
        exit 1
    fi
done

umask 077
if ! mkdir -p "$BACKUP_DIR"; then
    echo "Error: backup directory cannot be created by $(id -un): $BACKUP_DIR" >&2
    echo "Run instance.sh reconfigure or fix ownership to $EXPECTED_USER:$EXPECTED_USER mode 700." >&2
    exit 1
fi
if [[ ! -w "$BACKUP_DIR" ]]; then
    echo "Error: backup directory is not writable by $(id -un): $BACKUP_DIR" >&2
    echo "Run instance.sh reconfigure or fix ownership to $EXPECTED_USER:$EXPECTED_USER mode 700." >&2
    exit 1
fi
TODAY=$(date +%Y%m%d)
MONTH=$(date +%Y%m)
DAILY="$BACKUP_DIR/daily_$TODAY.sql.gz"
DAILY_TMP="$DAILY.tmp"
MONTHLY="$BACKUP_DIR/monthly_$MONTH.sql.gz"
MONTHLY_TMP="$MONTHLY.tmp"
DAILY_SHA="$BACKUP_DIR/daily_$TODAY.sha"
DAILY_SHA_TMP="$DAILY_SHA.tmp"
MONTHLY_SHA="$BACKUP_DIR/monthly_$MONTH.sha"
MONTHLY_SHA_TMP="$MONTHLY_SHA.tmp"
RELEASE_SHA_FILE="$INSTANCE_DIR/app/.release-sha"

if [[ ! -f "$RELEASE_SHA_FILE" ]]; then
    echo "Error: release SHA file not found at $RELEASE_SHA_FILE" >&2
    exit 1
fi
RELEASE_SHA="$(tr -d '[:space:]' < "$RELEASE_SHA_FILE")"
if [[ ! "$RELEASE_SHA" =~ ^[0-9a-f]{40}$ ]]; then
    echo "Error: invalid release SHA in $RELEASE_SHA_FILE: $RELEASE_SHA" >&2
    exit 1
fi

export PGPASSWORD="$DB_PASSWORD"

echo "Backing up $DB_NAME to $DAILY"
pg_dump -h "${DB_HOST:-/var/run/postgresql}" -p "${DB_PORT:-5432}" \
    -U "$DB_USER" "$DB_NAME" | gzip > "$DAILY_TMP"
printf '%s\n' "$RELEASE_SHA" > "$DAILY_SHA_TMP"
mv "$DAILY_TMP" "$DAILY"
mv "$DAILY_SHA_TMP" "$DAILY_SHA"

# Monthly backup on 1st
if [ "$(date +%d)" = "01" ]; then
    echo "Writing monthly copy $MONTHLY"
    cp "$DAILY" "$MONTHLY_TMP"
    printf '%s\n' "$RELEASE_SHA" > "$MONTHLY_SHA_TMP"
    mv "$MONTHLY_TMP" "$MONTHLY"
    mv "$MONTHLY_SHA_TMP" "$MONTHLY_SHA"
fi

echo "Applying retention and syncing to Google Drive"
"$SCRIPT_DIR/cleanup_backups.py" "$BACKUP_DIR" --delete
