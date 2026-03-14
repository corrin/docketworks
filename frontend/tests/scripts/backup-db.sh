#!/bin/bash
# Backup MySQL database before E2E tests

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

# Create backup directory if it doesn't exist
mkdir -p "$BACKUP_DIR"

# Generate timestamp for backup file
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/backup_${TIMESTAMP}.sql"

echo "Backing up database $MYSQL_DATABASE to $BACKUP_FILE..."

mysqldump \
    -h "$DB_HOST" \
    -P "$DB_PORT" \
    -u "$MYSQL_DB_USER" \
    -p"$DB_PASSWORD" \
    "$MYSQL_DATABASE" \
    > "$BACKUP_FILE"

echo "Backup complete: $BACKUP_FILE"

# Store the backup filename for restore script
echo "$BACKUP_FILE" > "$BACKUP_DIR/.latest_backup"

# Clean up old backups (keep last 5)
cd "$BACKUP_DIR"
ls -t backup_*.sql 2>/dev/null | tail -n +6 | xargs -r rm -f

echo "Database backup ready for E2E tests"
