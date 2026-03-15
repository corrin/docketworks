#!/bin/bash
set -euo pipefail

# Updates all instances: pulls code, updates shared deps, builds, migrates, restarts.
# Usage: sudo uat-deploy-shared.sh
#
# Steps:
#   1. git pull in each instance's code/
#   2. Check dep divergence across instances (pyproject.toml, package.json)
#   3. poetry install into shared venv
#   4. npm install into shared node_modules
#   5. Per-instance: npm run build, collectstatic, migrate, restart

BASE_DIR="/opt/docketworks"
INSTANCES_DIR="$BASE_DIR/instances"
SHARED_VENV="$BASE_DIR/.venv"
SHARED_NODE_MODULES="$BASE_DIR/node_modules"
SETUP_LOG="/var/log/docketworks-setup.log"

log() {
    local msg="[$(date '+%Y-%m-%d %H:%M:%S')] $*"
    echo "$msg" | tee -a "$SETUP_LOG"
}

if [[ $EUID -ne 0 ]]; then
    echo "ERROR: This script must be run as root (use sudo)."
    exit 1
fi

# --- Find all instances ---
INSTANCE_DIRS=()
for instance_dir in "$INSTANCES_DIR"/*/; do
    if [[ -f "$instance_dir/.env" && -d "$instance_dir/code/.git" ]]; then
        INSTANCE_DIRS+=("$instance_dir")
    fi
done

if [[ ${#INSTANCE_DIRS[@]} -eq 0 ]]; then
    echo "ERROR: No instances found in $INSTANCES_DIR"
    exit 1
fi

log "=========================================="
log "Deploying all instances"
log "  Found ${#INSTANCE_DIRS[@]} instance(s)"
log "=========================================="

# --- Pull latest code for all instances ---
for instance_dir in "${INSTANCE_DIRS[@]}"; do
    instance="$(basename "$instance_dir")"
    code_dir="$instance_dir/code"
    log "Pulling latest code for $instance..."
    sudo -u docketworks git -C "$code_dir" pull --ff-only
done

# --- Check dependency divergence ---
log "Checking for dependency divergence across instances..."
FIRST_DIR="${INSTANCE_DIRS[0]}code"
DIVERGED=false

if [[ ${#INSTANCE_DIRS[@]} -gt 1 ]]; then
    for instance_dir in "${INSTANCE_DIRS[@]:1}"; do
        instance="$(basename "$instance_dir")"
        code_dir="$instance_dir/code"

        if ! diff -q "$FIRST_DIR/pyproject.toml" "$code_dir/pyproject.toml" &>/dev/null; then
            log "  ERROR: pyproject.toml differs between $(basename "${INSTANCE_DIRS[0]}") and $instance"
            DIVERGED=true
        fi

        if ! diff -q "$FIRST_DIR/frontend/package.json" "$code_dir/frontend/package.json" &>/dev/null; then
            log "  ERROR: package.json differs between $(basename "${INSTANCE_DIRS[0]}") and $instance"
            DIVERGED=true
        fi
    done
fi

if $DIVERGED; then
    log "FATAL: Dependencies have diverged across instances. Resolve before deploying."
    log "  Shared venv and node_modules cannot serve divergent dependency sets."
    exit 1
fi

log "  Dependencies consistent across all instances."

# --- Update shared Python dependencies ---
log "Updating shared Python dependencies..."
sudo -u docketworks bash -c "
    export PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/opt/docketworks/.local/bin'
    source '$SHARED_VENV/bin/activate'
    pip install --upgrade pip
    cd '$FIRST_DIR'
    poetry install --no-interaction
"

# --- Update shared node_modules ---
log "Updating shared node_modules..."
sudo -u docketworks bash -c "
    cd '$FIRST_DIR/frontend'
    npm install --prefix '$BASE_DIR' --install-links
"

# --- Per-instance: build, collectstatic, migrate, restart ---
FAILED_INSTANCES=()
for instance_dir in "${INSTANCE_DIRS[@]}"; do
    instance="$(basename "$instance_dir")"
    code_dir="$instance_dir/code"

    log "--- Processing instance: $instance ---"

    # Build frontend
    log "  Building frontend..."
    sudo -u docketworks bash -c "
        cd '$code_dir/frontend'
        npm run build
    "

    # Collect static files
    log "  Collecting static files..."
    sudo -u docketworks bash -c "
        cd '$code_dir'
        source .venv/bin/activate
        set -a
        source '$instance_dir/.env'
        set +a
        python manage.py collectstatic --no-input
    "

    # Run migrations
    log "  Running migrations..."
    if sudo -u docketworks bash -c "
        cd '$code_dir'
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

    # Restart gunicorn
    if systemctl is-enabled "gunicorn-$instance" &>/dev/null; then
        log "  Restarting gunicorn-$instance"
        systemctl restart "gunicorn-$instance"
    fi
done

# --- Summary ---
log "=========================================="
log "Deploy complete"
if [[ ${#FAILED_INSTANCES[@]} -gt 0 ]]; then
    log "  WARNING: Migrations failed for: ${FAILED_INSTANCES[*]}"
fi
log "=========================================="
