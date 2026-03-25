#!/bin/bash
set -euo pipefail

# Create or reset a PostgreSQL database and user for docketworks.
#
# Development (reads from .env):
#   ./scripts/setup_database.sh [--drop]
#
# UAT/Production (explicit arguments):
#   ./scripts/setup_database.sh --db <name> --user <user> --password <pass> [--drop]

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

DB_NAME=""
DB_USER=""
DB_PASSWORD=""
DROP=false

# --- Parse arguments ---
while [[ $# -gt 0 ]]; do
    case "$1" in
        --db)       DB_NAME="$2"; shift 2 ;;
        --user)     DB_USER="$2"; shift 2 ;;
        --password) DB_PASSWORD="$2"; shift 2 ;;
        --drop)     DROP=true; shift ;;
        *)          echo "Unknown option: $1"; exit 1 ;;
    esac
done

# --- Fall back to .env if arguments not provided ---
if [[ -z "$DB_NAME" || -z "$DB_USER" || -z "$DB_PASSWORD" ]]; then
    ENV_FILE="$PROJECT_DIR/.env"
    if [[ ! -f "$ENV_FILE" ]]; then
        echo "Error: No arguments provided and no .env found at $ENV_FILE"
        echo "Usage: $0 --db <name> --user <user> --password <pass> [--drop]"
        exit 1
    fi
    DB_NAME="${DB_NAME:-$(grep -E '^DB_NAME=' "$ENV_FILE" | cut -d= -f2)}"
    DB_USER="${DB_USER:-$(grep -E '^DB_USER=' "$ENV_FILE" | cut -d= -f2)}"
    DB_PASSWORD="${DB_PASSWORD:-$(grep -E '^DB_PASSWORD=' "$ENV_FILE" | cut -d= -f2)}"
fi

if [[ -z "$DB_NAME" || -z "$DB_USER" || -z "$DB_PASSWORD" ]]; then
    echo "Error: DB_NAME, DB_USER, and DB_PASSWORD are all required."
    exit 1
fi

echo "Database: $DB_NAME"
echo "User:     $DB_USER"
echo "Drop:     $DROP"

# --- Drop if requested ---
if [[ "$DROP" == "true" ]]; then
    echo "Dropping database $DB_NAME (if exists)..."
    sudo -u postgres psql -c "DROP DATABASE IF EXISTS \"$DB_NAME\";"
    echo "Dropping role $DB_USER (if exists)..."
    sudo -u postgres psql -c "DROP ROLE IF EXISTS \"$DB_USER\";"
fi

# --- Create role and database ---
echo "Creating role $DB_USER..."
sudo -u postgres psql <<EOSQL
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '$DB_USER') THEN
        CREATE ROLE "$DB_USER" WITH LOGIN PASSWORD '$DB_PASSWORD';
    ELSE
        ALTER ROLE "$DB_USER" WITH PASSWORD '$DB_PASSWORD';
    END IF;
END
\$\$;
EOSQL

echo "Creating database $DB_NAME..."
sudo -u postgres psql <<EOSQL
SELECT 'CREATE DATABASE "$DB_NAME" OWNER "$DB_USER"'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '$DB_NAME')\gexec
GRANT ALL PRIVILEGES ON DATABASE "$DB_NAME" TO "$DB_USER";
EOSQL

echo "Database $DB_NAME ready."
