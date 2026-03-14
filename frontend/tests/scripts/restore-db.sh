#!/bin/bash
# Restore MySQL database after E2E tests

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="$SCRIPT_DIR/../.."
BACKUP_DIR="$SCRIPT_DIR/../backups"

# Load BACKEND_ENV_PATH from frontend .env
if [ -f "$FRONTEND_DIR/.env" ]; then
    BACKEND_ENV_PATH=$(grep -E '^BACKEND_ENV_PATH=' "$FRONTEND_DIR/.env" | cut -d'=' -f2)
fi

if [ -z "$BACKEND_ENV_PATH" ] || [ ! -f "$BACKEND_ENV_PATH" ]; then
    echo "Error: Backend .env not found. Set BACKEND_ENV_PATH in frontend .env"
    exit 1
fi

# Source database credentials from backend .env
export $(grep -E '^(MYSQL_DATABASE|MYSQL_DB_USER|DB_PASSWORD|DB_HOST|DB_PORT)=' "$BACKEND_ENV_PATH" | xargs)

# Set defaults
DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-3306}"

# Get the latest backup file
if [ ! -f "$BACKUP_DIR/.latest_backup" ]; then
    echo "Error: No backup found. Run backup-db.sh first."
    exit 1
fi

BACKUP_FILE=$(cat "$BACKUP_DIR/.latest_backup")

if [ ! -f "$BACKUP_FILE" ]; then
    echo "Error: Backup file not found: $BACKUP_FILE"
    exit 1
fi

echo "Restoring database $MYSQL_DATABASE from $BACKUP_FILE..."

mysql \
    -h "$DB_HOST" \
    -P "$DB_PORT" \
    -u "$MYSQL_DB_USER" \
    -p"$DB_PASSWORD" \
    "$MYSQL_DATABASE" \
    < "$BACKUP_FILE"

echo "Database restored successfully"
