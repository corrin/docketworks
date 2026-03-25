#!/bin/bash
set -euo pipefail

# Usage: backup_db.sh <instance>
# Example: backup_db.sh msm

if [[ $# -lt 1 ]]; then
    echo "Usage: $0 <instance>"
    echo "Example: $0 msm"
    exit 1
fi

INSTANCE="$1"
INSTANCE_DIR="/opt/docketworks/instances/$INSTANCE"
BACKUP_DIR="$INSTANCE_DIR/backups"
ENV_FILE="$INSTANCE_DIR/.env"

if [[ ! -f "$ENV_FILE" ]]; then
    echo "Error: .env not found at $ENV_FILE" >&2
    exit 1
fi

# Read DB_NAME from instance .env
DB_NAME=$(grep -E '^DB_NAME=' "$ENV_FILE" | cut -d= -f2)
if [[ -z "$DB_NAME" ]]; then
    echo "Error: DB_NAME not set in $ENV_FILE" >&2
    exit 1
fi

mkdir -p "$BACKUP_DIR"
TODAY=$(date +%Y%m%d)
MONTH=$(date +%Y%m)

# Daily backup with compression
sudo -u postgres pg_dump "$DB_NAME" | gzip > "$BACKUP_DIR/daily_$TODAY.sql.gz"

# Monthly backup on 1st
if [ "$(date +%d)" = "01" ]; then
    cp "$BACKUP_DIR/daily_$TODAY.sql.gz" "$BACKUP_DIR/monthly_$MONTH.sql.gz"
fi

# Sync to Google Drive
rclone copy "$BACKUP_DIR" gdrive:dw_backups/
