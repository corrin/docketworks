#!/bin/bash
set -euo pipefail

# Usage: rollback_release.sh <instance> <backup_timestamp>
# Example: rollback_release.sh msm 20250130_221922

if [[ $# -lt 2 ]]; then
  echo "Usage: $0 <instance> <backup_timestamp>"
  echo "Example: $0 msm 20250130_221922"
  exit 1
fi

INSTANCE="$1"
BACKUP_TIMESTAMP="$2"
INSTANCE_DIR="/opt/docketworks/instances/$INSTANCE"
INSTANCE_USER="dw-$INSTANCE"
BACKUP_DIR="$INSTANCE_DIR/backups"
DATE_DIR="$BACKUP_DIR/$BACKUP_TIMESTAMP"
CODE_BACKUP="$DATE_DIR/code_${BACKUP_TIMESTAMP}.tgz"
DB_BACKUP="$DATE_DIR/db_${BACKUP_TIMESTAMP}.sql.gz"
CODE_DIR="$INSTANCE_DIR/code"
SERVICE="gunicorn-$INSTANCE"
ENV_FILE="$INSTANCE_DIR/.env"

# Read DB_NAME from instance .env
DB_NAME=$(grep -E '^DB_NAME=' "$ENV_FILE" | cut -d= -f2)
if [[ -z "$DB_NAME" ]]; then
  echo "ERROR: DB_NAME not set in $ENV_FILE" >&2
  exit 1
fi

# 1) Ensure backups actually exist
if [[ ! -f "$CODE_BACKUP" ]]; then
  echo "ERROR: Code backup not found: $CODE_BACKUP"
  exit 1
fi
if [[ ! -f "$DB_BACKUP" ]]; then
  echo "ERROR: DB backup not found: $DB_BACKUP"
  exit 1
fi

# 2) Stop Gunicorn
echo "=== Stopping $SERVICE..."
systemctl stop "$SERVICE"

# 3) Remove current code
echo "=== Removing existing code at $CODE_DIR..."
rm -rf "$CODE_DIR"

# 4) Restore code from tarball
echo "=== Restoring code from $CODE_BACKUP..."
tar -zxf "$CODE_BACKUP" -C "$INSTANCE_DIR"
chown -R "$INSTANCE_USER:$INSTANCE_USER" "$CODE_DIR"

# 5) Restore DB
echo "=== Restoring DB from $DB_BACKUP..."
gunzip < "$DB_BACKUP" | sudo -u postgres psql "$DB_NAME"

# 6) Restart Gunicorn
echo "=== Starting $SERVICE..."
systemctl start "$SERVICE"

echo "=== Rollback complete. Verify the site is now running the older version! ==="
