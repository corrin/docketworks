#!/bin/bash
set -euo pipefail

# Deploys latest code to an existing UAT/demo instance.
# Usage: uat-deploy-instance.sh <name>

DOMAIN="docketworks.site"
BASE_DIR="/opt/docketworks"

if [[ $# -ne 1 ]]; then
    echo "Usage: $0 <instance-name>"
    exit 1
fi

INSTANCE="$1"
INSTANCE_DIR="$BASE_DIR/$INSTANCE"

if [[ ! -d "$INSTANCE_DIR" ]]; then
    echo "ERROR: Instance directory $INSTANCE_DIR does not exist."
    exit 1
fi

echo "=== Deploying instance: $INSTANCE ==="

# --- Pull latest code ---
echo "=== Pulling latest code ==="
sudo -u docketworks bash -c "
    cd '$INSTANCE_DIR'
    git pull
"

# --- Update Python dependencies ---
echo "=== Updating Python dependencies ==="
sudo -u docketworks bash -c "
    cd '$INSTANCE_DIR'
    source .venv/bin/activate
    poetry install --no-interaction
"

# --- Run migrations ---
echo "=== Running migrations ==="
sudo -u docketworks bash -c "
    cd '$INSTANCE_DIR'
    source .venv/bin/activate
    python manage.py migrate --no-input
    python manage.py collectstatic --no-input
"

# --- Rebuild frontend ---
echo "=== Building frontend ==="
sudo -u docketworks bash -c "
    cd '$INSTANCE_DIR/frontend'
    npm install
    VITE_API_BASE_URL='https://$INSTANCE.$DOMAIN' npm run build
"

# --- Restart Gunicorn ---
echo "=== Restarting Gunicorn ==="
systemctl restart "gunicorn-$INSTANCE"

echo ""
echo "=== Instance '$INSTANCE' deployed successfully ==="
echo "  URL: https://$INSTANCE.$DOMAIN"
