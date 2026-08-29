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
APP_DIR="$INSTANCE_DIR/app"

export PGPASSWORD="$DB_PASSWORD"

echo "Backing up $DB_NAME to $DAILY"
pg_dump -h "${DB_HOST:-/var/run/postgresql}" -p "${DB_PORT:-5432}" \
    -U "$DB_USER" "$DB_NAME" | gzip > "$DAILY_TMP"
mv "$DAILY_TMP" "$DAILY"

# Fable: the monthly dump copies BEFORE the sidecar step — it is written only
# on the 1st, so a sidecar failure aborting the run must not cost the month
# its monthly backup.
if [ "$(date +%d)" = "01" ]; then
    echo "Writing monthly copy $MONTHLY"
    cp "$DAILY" "$MONTHLY_TMP"
    mv "$MONTHLY_TMP" "$MONTHLY"
fi

# Fable: this is the sidecar restores actually consume (migrate_to_snapshot.py): which
# migration state this dump matches. The retired .sha sidecar recorded the
# release commit instead, which no restore path ever read.
# Fable: read AFTER pg_dump deliberately, not in one coordinated snapshot: a
# migration committing in between makes the sidecar LEAD the dump, and
# migrate_to_snapshot migrates the restored database up to the sidecar, so
# that direction is consumed correctly. Only a rollback inside this
# seconds-wide midnight window would mislead, and migrations only run at
# deploys, which take predeploy_backup first.
(cd "$APP_DIR" && .venv/bin/python manage.py snapshot_migrations --dump "$DAILY")

if [ "$(date +%d)" = "01" ]; then
    cp "$DAILY.migrations.json" "$MONTHLY.migrations.json.tmp"
    mv "$MONTHLY.migrations.json.tmp" "$MONTHLY.migrations.json"
fi

echo "Applying retention and syncing to Google Drive"
"$SCRIPT_DIR/cleanup_backups.py" "$BACKUP_DIR" --delete
