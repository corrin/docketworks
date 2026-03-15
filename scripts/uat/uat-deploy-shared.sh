#!/bin/bash
set -euo pipefail

# Updates the shared codebase and deploys to all instances.
# Usage: sudo uat-deploy-shared.sh
#
# Steps:
#   1. git pull in shared/
#   2. poetry install (picks up new deps)
#   3. npm install && npm run build (one frontend build)
#   4. collectstatic
#   5. migrate each instance
#   6. restart all gunicorn services

BASE_DIR="/opt/docketworks"
SHARED_DIR="$BASE_DIR/shared"
INSTANCES_DIR="$BASE_DIR/instances"
SETUP_LOG="/var/log/docketworks-setup.log"

log() {
    local msg="[$(date '+%Y-%m-%d %H:%M:%S')] $*"
    echo "$msg" | tee -a "$SETUP_LOG"
}

if [[ $EUID -ne 0 ]]; then
    echo "ERROR: This script must be run as root (use sudo)."
    exit 1
fi

if [[ ! -d "$SHARED_DIR/.git" ]]; then
    echo "ERROR: Shared codebase not found at $SHARED_DIR"
    echo "Run uat-base-setup.sh first."
    exit 1
fi

log "=========================================="
log "Deploying shared codebase"
log "=========================================="

# --- Pull latest code ---
log "Pulling latest code..."
sudo -u docketworks git -C "$SHARED_DIR" pull --ff-only

# --- Update Python dependencies ---
log "Updating Python dependencies..."
sudo -u docketworks bash -c "
    cd '$SHARED_DIR'
    source .venv/bin/activate
    pip install --upgrade pip
    export PATH='/opt/docketworks/.local/bin:\$PATH'
    poetry install --no-interaction
"

# --- Build frontend ---
log "Building frontend..."
sudo -u docketworks bash -c "
    cd '$SHARED_DIR/frontend'
    npm install
    npm run build
"

# --- Collect static files ---
log "Collecting static files..."
sudo -u docketworks bash -c "
    cd '$SHARED_DIR'
    source .venv/bin/activate
    python manage.py collectstatic --no-input
"

# --- Migrate each instance ---
FAILED_INSTANCES=()
for instance_dir in "$INSTANCES_DIR"/*/; do
    if [[ ! -f "$instance_dir/.env" ]]; then
        continue
    fi
    instance="$(basename "$instance_dir")"
    log "Running migrations for instance: $instance"
    if sudo -u docketworks bash -c "
        cd '$SHARED_DIR'
        source .venv/bin/activate
        set -a
        source '$instance_dir/.env'
        set +a
        python manage.py migrate --no-input
    "; then
        log "  Migrations complete for $instance"
    else
        log "  ERROR: Migrations failed for $instance"
        FAILED_INSTANCES+=("$instance")
    fi
done

# --- Restart all gunicorn services ---
log "Restarting all gunicorn services..."
for instance_dir in "$INSTANCES_DIR"/*/; do
    if [[ ! -f "$instance_dir/.env" ]]; then
        continue
    fi
    instance="$(basename "$instance_dir")"
    if systemctl is-enabled "gunicorn-$instance" &>/dev/null; then
        log "  Restarting gunicorn-$instance"
        systemctl restart "gunicorn-$instance"
    fi
done

# --- Summary ---
log "=========================================="
log "Shared deploy complete"
if [[ ${#FAILED_INSTANCES[@]} -gt 0 ]]; then
    log "  WARNING: Migrations failed for: ${FAILED_INSTANCES[*]}"
fi
log "=========================================="
