#!/bin/bash
set -euo pipefail

# Create (or reset) a MySQL/MariaDB database and user for docketworks.
# Single source of truth — used by both local dev and UAT instance scripts.
#
# Usage:
#   Dev (reads from .env, drops first):
#     sudo ./scripts/setup_database.sh --drop
#
#   UAT (explicit args, no drop):
#     ./scripts/setup_database.sh --db dw_msm_uat --user dw_msm_uat --password xxx --host localhost

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

DB_NAME=""
DB_USER=""
DB_PASSWORD=""
DB_HOST="%"
DROP=false

# --- Parse arguments ---
while [[ $# -gt 0 ]]; do
    case "$1" in
        --db)       DB_NAME="$2"; shift 2 ;;
        --user)     DB_USER="$2"; shift 2 ;;
        --password) DB_PASSWORD="$2"; shift 2 ;;
        --host)     DB_HOST="$2"; shift 2 ;;
        --drop)     DROP=true; shift ;;
        *)          echo "Unknown option: $1"; exit 1 ;;
    esac
done

# --- Fill missing values from .env ---
if [[ -z "$DB_NAME" || -z "$DB_USER" || -z "$DB_PASSWORD" ]]; then
    ENV_FILE="$PROJECT_DIR/.env"
    if [[ ! -f "$ENV_FILE" ]]; then
        echo "ERROR: --db/--user/--password not provided and no .env found at $ENV_FILE"
        exit 1
    fi
    [[ -z "$DB_NAME" ]]     && DB_NAME="$(grep '^MYSQL_DATABASE=' "$ENV_FILE" | cut -d= -f2)"
    [[ -z "$DB_USER" ]]     && DB_USER="$(grep '^MYSQL_DB_USER=' "$ENV_FILE" | cut -d= -f2)"
    [[ -z "$DB_PASSWORD" ]] && DB_PASSWORD="$(grep '^DB_PASSWORD=' "$ENV_FILE" | cut -d= -f2)"
fi

if [[ -z "$DB_NAME" || -z "$DB_USER" || -z "$DB_PASSWORD" ]]; then
    echo "ERROR: Missing required database parameters (db, user, password)."
    echo "Provide via flags or ensure MYSQL_DATABASE, MYSQL_DB_USER, DB_PASSWORD are in .env"
    exit 1
fi

TEST_DB_NAME="test_${DB_NAME}"

echo "Setting up database: $DB_NAME"
echo "  User:    $DB_USER@$DB_HOST"
echo "  Test DB: $TEST_DB_NAME"
echo "  Drop:    $DROP"
echo ""

# --- Build SQL ---
SQL=""

if [[ "$DROP" == "true" ]]; then
    SQL+="DROP DATABASE IF EXISTS \`$DB_NAME\`;"$'\n'
    SQL+="DROP USER IF EXISTS '$DB_USER'@'$DB_HOST';"$'\n'
fi

SQL+="CREATE DATABASE IF NOT EXISTS \`$DB_NAME\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"$'\n'
SQL+="DROP USER IF EXISTS '$DB_USER'@'$DB_HOST';"$'\n'
SQL+="CREATE USER '$DB_USER'@'$DB_HOST' IDENTIFIED BY '$DB_PASSWORD';"$'\n'
SQL+="GRANT ALL PRIVILEGES ON \`$DB_NAME\`.* TO '$DB_USER'@'$DB_HOST';"$'\n'
SQL+="GRANT ALL PRIVILEGES ON \`$TEST_DB_NAME\`.* TO '$DB_USER'@'$DB_HOST';"$'\n'
SQL+="FLUSH PRIVILEGES;"$'\n'

mysql -u root <<< "$SQL"

echo ""
echo "Database $DB_NAME setup complete."
