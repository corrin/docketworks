#!/bin/bash
# Backup PostgreSQL database before E2E tests

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="$SCRIPT_DIR/../.."
BACKUP_DIR="$SCRIPT_DIR/../../../restore/e2e"

# Backend .env is always one level up from frontend/
BACKEND_ENV_PATH="$FRONTEND_DIR/../.env"

if [ ! -f "$BACKEND_ENV_PATH" ]; then
    echo "Error: Backend .env not found at $BACKEND_ENV_PATH"
    exit 1
fi

# Source database credentials from backend .env
set -a; source "$BACKEND_ENV_PATH"; set +a

if [ -z "${DB_HOST:-}" ]; then
    echo "Error: DB_HOST must be set in $BACKEND_ENV_PATH"
    exit 1
fi

# DB_PORT is required for TCP connections, optional for Unix sockets
if [[ ! "$DB_HOST" == /* ]] && [ -z "${DB_PORT:-}" ]; then
    echo "Error: DB_PORT must be set in $BACKEND_ENV_PATH for TCP connections"
    exit 1
fi

# Create backup directory if it doesn't exist
mkdir -p "$BACKUP_DIR"

# Generate timestamp for backup file
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/backup_${TIMESTAMP}.sql"

echo "Backing up database $DB_NAME to $BACKUP_FILE..."

PG_DUMP_ARGS=(--clean -h "$DB_HOST")
if [ -n "${DB_PORT:-}" ]; then
    PG_DUMP_ARGS+=(-p "$DB_PORT")
fi
PG_DUMP_ARGS+=(-U "$DB_USER" "$DB_NAME")

PGPASSWORD="$DB_PASSWORD" pg_dump "${PG_DUMP_ARGS[@]}" > "$BACKUP_FILE"

echo "Backup complete: $BACKUP_FILE"

# Store the backup filename for restore script
echo "$BACKUP_FILE" > "$BACKUP_DIR/.latest_backup"

# Clean up old backups (keep last 5)
cd "$BACKUP_DIR"
ls -t backup_*.sql 2>/dev/null | tail -n +6 | xargs -r rm -f

echo "Database backup ready for E2E tests"
