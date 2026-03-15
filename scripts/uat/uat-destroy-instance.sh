#!/bin/bash
set -euo pipefail

# Destroys a UAT/demo instance — removes files, database, systemd service, and Nginx config.
# Usage: uat-destroy-instance.sh <name>

BASE_DIR="/opt/docketworks"

if [[ $# -ne 1 ]]; then
    echo "Usage: $0 <instance-name>"
    exit 1
fi

INSTANCE="$1"
INSTANCE_DIR="$BASE_DIR/$INSTANCE"
DB_NAME="docketworks_${INSTANCE//-/_}"
DB_USER="docketworks_${INSTANCE//-/_}"

echo "=== Destroying instance: $INSTANCE ==="
echo ""
echo "  This will permanently delete:"
echo "    - Directory: $INSTANCE_DIR"
echo "    - Database:  $DB_NAME"
echo "    - Service:   gunicorn-$INSTANCE"
echo "    - Nginx:     docketworks-$INSTANCE"
echo ""
read -p "Are you sure? (yes/no): " CONFIRM
if [[ "$CONFIRM" != "yes" ]]; then
    echo "Aborted."
    exit 0
fi

# --- Stop and remove systemd service ---
if systemctl is-active --quiet "gunicorn-$INSTANCE" 2>/dev/null; then
    echo "=== Stopping Gunicorn service ==="
    systemctl stop "gunicorn-$INSTANCE"
fi
if [[ -f "/etc/systemd/system/gunicorn-$INSTANCE.service" ]]; then
    echo "=== Removing systemd service ==="
    systemctl disable "gunicorn-$INSTANCE" 2>/dev/null || true
    rm -f "/etc/systemd/system/gunicorn-$INSTANCE.service"
    systemctl daemon-reload
fi

# --- Remove Nginx config ---
if [[ -f "/etc/nginx/sites-available/docketworks-$INSTANCE" ]]; then
    echo "=== Removing Nginx config ==="
    rm -f "/etc/nginx/sites-enabled/docketworks-$INSTANCE"
    rm -f "/etc/nginx/sites-available/docketworks-$INSTANCE"
    nginx -t && systemctl reload nginx
fi

# --- Drop database and user ---
echo "=== Dropping database and user ==="
mysql -u root <<EOSQL || true
DROP DATABASE IF EXISTS \`$DB_NAME\`;
DROP USER IF EXISTS '$DB_USER'@'localhost';
FLUSH PRIVILEGES;
EOSQL

# --- Remove files ---
if [[ -d "$INSTANCE_DIR" ]]; then
    echo "=== Removing instance directory ==="
    rm -rf "$INSTANCE_DIR"
fi

echo ""
echo "=== Instance '$INSTANCE' destroyed ==="
