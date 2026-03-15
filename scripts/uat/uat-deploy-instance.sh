#!/bin/bash
set -euo pipefail

# Deploys a single UAT/demo instance — pulls code, builds, collectstatic, migrates, restarts.
# Usage: uat-deploy-instance.sh <name>

DOMAIN="docketworks.site"
BASE_DIR="/opt/docketworks"
INSTANCES_DIR="$BASE_DIR/instances"

if [[ $# -ne 1 ]]; then
    echo "Usage: $0 <instance-name>"
    exit 1
fi

INSTANCE="$1"
INSTANCE_DIR="$INSTANCES_DIR/$INSTANCE"
CODE_DIR="$INSTANCE_DIR/code"

if [[ ! -d "$INSTANCE_DIR" ]]; then
    echo "ERROR: Instance directory $INSTANCE_DIR does not exist."
    exit 1
fi

if [[ ! -f "$INSTANCE_DIR/.env" ]]; then
    echo "ERROR: No .env file found at $INSTANCE_DIR/.env"
    exit 1
fi

if [[ ! -d "$CODE_DIR/.git" ]]; then
    echo "ERROR: No git repo found at $CODE_DIR"
    exit 1
fi

echo "=== Deploying instance: $INSTANCE ==="

# --- Pull latest code ---
echo "=== Pulling latest code ==="
sudo -u docketworks git -C "$CODE_DIR" pull --ff-only

# --- Build frontend ---
echo "=== Building frontend ==="
sudo -u docketworks bash -c "
    cd '$CODE_DIR/frontend'
    npm run build
"

# --- Collect static files ---
echo "=== Collecting static files ==="
sudo -u docketworks bash -c "
    cd '$CODE_DIR'
    source .venv/bin/activate
    set -a
    source '$INSTANCE_DIR/.env'
    set +a
    python manage.py collectstatic --no-input
"

# --- Run migrations ---
echo "=== Running migrations ==="
sudo -u docketworks bash -c "
    cd '$CODE_DIR'
    source .venv/bin/activate
    set -a
    source '$INSTANCE_DIR/.env'
    set +a
    python manage.py migrate --no-input
"

# --- Restart Gunicorn ---
echo "=== Restarting Gunicorn ==="
systemctl restart "gunicorn-$INSTANCE"

echo ""
echo "=== Instance '$INSTANCE' deployed successfully ==="
echo "  URL: https://$INSTANCE.$DOMAIN"
