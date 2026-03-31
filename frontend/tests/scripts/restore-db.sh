#!/bin/bash
# Restore PostgreSQL database after E2E tests

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="$SCRIPT_DIR/../.."
BACKUP_DIR="$SCRIPT_DIR/../backups"

# Backend .env is always one level up from frontend/
BACKEND_ENV_PATH="$FRONTEND_DIR/../.env"

if [ ! -f "$BACKEND_ENV_PATH" ]; then
    echo "Error: Backend .env not found at $BACKEND_ENV_PATH"
    exit 1
fi

# Source database credentials from backend .env
set -a; source "$BACKEND_ENV_PATH"; set +a

if [ -z "${DB_HOST:-}" ] || [ -z "${DB_PORT:-}" ]; then
    echo "Error: DB_HOST and DB_PORT must be set in $BACKEND_ENV_PATH"
    exit 1
fi

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

echo "Restoring database $DB_NAME from $BACKUP_FILE..."

PGPASSWORD="$DB_PASSWORD" psql \
    -h "$DB_HOST" \
    -p "$DB_PORT" \
    -U "$DB_USER" \
    "$DB_NAME" \
    < "$BACKUP_FILE"

echo "Database restored successfully"
