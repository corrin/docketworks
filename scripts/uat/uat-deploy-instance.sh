#!/bin/bash
set -euo pipefail

# Deploys (migrates + restarts) a single UAT/demo instance.
# For updating the shared codebase (git pull, build, etc.), use uat-deploy-shared.sh.
# Usage: uat-deploy-instance.sh <name>

DOMAIN="docketworks.site"
BASE_DIR="/opt/docketworks"
SHARED_DIR="$BASE_DIR/shared"
INSTANCES_DIR="$BASE_DIR/instances"

if [[ $# -ne 1 ]]; then
    echo "Usage: $0 <instance-name>"
    exit 1
fi

INSTANCE="$1"
INSTANCE_DIR="$INSTANCES_DIR/$INSTANCE"

if [[ ! -d "$INSTANCE_DIR" ]]; then
    echo "ERROR: Instance directory $INSTANCE_DIR does not exist."
    exit 1
fi

if [[ ! -f "$INSTANCE_DIR/.env" ]]; then
    echo "ERROR: No .env file found at $INSTANCE_DIR/.env"
    exit 1
fi

echo "=== Deploying instance: $INSTANCE ==="

# --- Run migrations ---
echo "=== Running migrations ==="
sudo -u docketworks bash -c "
    cd '$SHARED_DIR'
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
