#!/bin/bash
set -euo pipefail

# One-time migration script: MariaDB → PostgreSQL
#
# Usage: sudo ./scripts/migrate_mariadb_to_postgres.sh <instance>
# Example: sudo ./scripts/migrate_mariadb_to_postgres.sh msm
#
# Prerequisites:
#   - PostgreSQL installed and running
#   - Instance .env already updated with DB_NAME, DB_USER, DB_PORT=5432
#   - MariaDB still running (for the dump step)
#
# This script:
#   1. Stops gunicorn
#   2. Dumps data from MariaDB via Django dumpdata
#   3. Creates the Postgres database
#   4. Runs Django migrate to create schema
#   5. Loads data into Postgres
#   6. Verifies row counts
#   7. Restarts gunicorn

if [[ $EUID -ne 0 ]]; then
    echo "ERROR: This script must be run as root (use sudo)."
    exit 1
fi

if [[ $# -ne 1 ]]; then
    echo "Usage: $0 <instance>"
    echo "Example: $0 msm"
    exit 1
fi

INSTANCE="$1"
INSTANCE_DIR="/opt/docketworks/instances/$INSTANCE"
ENV_FILE="$INSTANCE_DIR/.env"
CODE_DIR="$INSTANCE_DIR/code"
SERVICE="gunicorn-$INSTANCE"
SHARED_VENV="/opt/docketworks/.venv"
INSTANCE_USER="dw-$INSTANCE"
DUMP_FILE="/tmp/dw_${INSTANCE}_dump.json"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [[ ! -f "$ENV_FILE" ]]; then
    echo "ERROR: .env not found at $ENV_FILE"
    exit 1
fi

# Read database config
DB_NAME=$(grep -E '^DB_NAME=' "$ENV_FILE" | cut -d= -f2)
DB_USER=$(grep -E '^DB_USER=' "$ENV_FILE" | cut -d= -f2)
DB_PASSWORD=$(grep -E '^DB_PASSWORD=' "$ENV_FILE" | cut -d= -f2)

if [[ -z "$DB_NAME" || -z "$DB_USER" ]]; then
    echo "ERROR: DB_NAME and DB_USER must be set in $ENV_FILE"
    exit 1
fi

# Helper to run Django commands as the instance user
dw_run() {
    sudo -u "$INSTANCE_USER" bash -c "
        source '$SHARED_VENV/bin/activate'
        set -a; source '$ENV_FILE'; set +a
        cd '$CODE_DIR'
        $*
    "
}

echo "=========================================="
echo "MariaDB → PostgreSQL Migration"
echo "=========================================="
echo "Instance:  $INSTANCE"
echo "Database:  $DB_NAME"
echo "Dump file: $DUMP_FILE"
echo ""

# --- Step 1: Stop gunicorn ---
echo "=== Step 1: Stopping $SERVICE..."
systemctl stop "$SERVICE"

# --- Step 2: Dump data from MariaDB ---
echo "=== Step 2: Dumping data from MariaDB..."
echo "  (This uses the CURRENT database config — ensure MariaDB env vars are still set)"
dw_run python manage.py dumpdata \
    --natural-foreign --natural-primary \
    --exclude contenttypes --exclude auth.permission \
    --exclude admin.logentry \
    --indent 2 \
    --output "$DUMP_FILE"
echo "  Dump complete: $(wc -c < "$DUMP_FILE") bytes"

# --- Step 3: Create Postgres database ---
echo "=== Step 3: Creating Postgres database..."
"$SCRIPT_DIR/setup_database.sh" \
    --db "$DB_NAME" \
    --user "$DB_USER" \
    --password "$DB_PASSWORD" \
    --drop

# --- Step 4: Run Django migrate ---
echo "=== Step 4: Running Django migrate on Postgres..."
dw_run python manage.py migrate --no-input

# --- Step 5: Load data ---
echo "=== Step 5: Loading data into Postgres..."
dw_run python manage.py loaddata "$DUMP_FILE"

# --- Step 6: Verify ---
echo "=== Step 6: Verifying row counts..."
dw_run python -c "
from django.apps import apps
total = 0
for model in sorted(apps.get_models(), key=lambda m: m._meta.label):
    count = model.objects.count()
    if count > 0:
        print(f'  {model._meta.label}: {count}')
        total += count
print(f'  TOTAL: {total}')
"

# --- Step 7: Restart gunicorn ---
echo "=== Step 7: Restarting $SERVICE..."
systemctl start "$SERVICE"

echo ""
echo "=========================================="
echo "Migration complete!"
echo "=========================================="
echo "  Verify the site at: https://$INSTANCE.docketworks.site"
echo "  Dump file preserved at: $DUMP_FILE"
echo ""
echo "  Once verified, you can remove MariaDB:"
echo "    apt remove --purge mariadb-server"
