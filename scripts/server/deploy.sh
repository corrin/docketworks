#!/bin/bash
set -euo pipefail

# Deploy one or all instances.
# Usage: deploy.sh <name>       — deploy a single instance
#        deploy.sh --all        — deploy all instances
#
# Steps:
#   1. Git pull per-instance code
#   2. Update shared deps (poetry install, npm install)
#   3. Per-instance: npm run build, migrate, restart

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/common.sh"

if [[ $EUID -ne 0 ]]; then
    echo "ERROR: This script must be run as root (use sudo)."
    exit 1
fi

if [[ $# -lt 1 ]]; then
    echo "Usage: $0 <instance-name|--all>"
    exit 1
fi

# --- Determine which instances to deploy ---
TARGETS=()
if [[ "$1" == "--all" ]]; then
    for instance_dir in "$INSTANCES_DIR"/*/; do
        [[ -d "$instance_dir" ]] || continue
        if [[ -f "$instance_dir/.env" && -d "$instance_dir/.git" ]]; then
            TARGETS+=("$(basename "$instance_dir")")
        fi
    done
    if [[ ${#TARGETS[@]} -eq 0 ]]; then
        echo "ERROR: No instances found in $INSTANCES_DIR"
        exit 1
    fi
else
    TARGETS=("$1")
    local_dir="$INSTANCES_DIR/$1"
    if [[ ! -d "$local_dir" ]]; then
        echo "ERROR: Instance directory $local_dir does not exist."
        exit 1
    fi
    if [[ ! -f "$local_dir/.env" ]]; then
        echo "ERROR: No .env file found at $local_dir/.env"
        exit 1
    fi
    if [[ ! -d "$local_dir/.git" ]]; then
        echo "ERROR: No git repo found at $local_dir"
        exit 1
    fi
fi

log "=========================================="
log "Deploying: ${TARGETS[*]}"
log "=========================================="

# --- Update local repo from GitHub ---
log "Pulling latest from GitHub into local repo..."
sudo -u docketworks git -C "$LOCAL_REPO" pull --ff-only

# --- Pull latest code for all target instances (from local repo) ---
for instance in "${TARGETS[@]}"; do
    inst_dir="$INSTANCES_DIR/$instance"
    inst_user="$(instance_user "$instance")"
    log "Pulling latest code for $instance..."
    sudo -u "$inst_user" git -C "$inst_dir" fetch origin
    sudo -u "$inst_user" git -C "$inst_dir" pull --ff-only
done

# --- Update shared Python dependencies (from local repo) ---
log "Updating shared Python dependencies..."
sudo -u docketworks bash -c "
    export PATH='/opt/docketworks/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
    export POETRY_VIRTUALENVS_CREATE=false
    source '$SHARED_VENV/bin/activate'
    pip install --upgrade pip
    cd '$LOCAL_REPO'
    poetry install --no-interaction
"

# --- Update shared node_modules ---
log "Updating shared node_modules..."
sudo -u docketworks bash -c "
    cp '$LOCAL_REPO/frontend/package.json' '$BASE_DIR/package.json'
    cp '$LOCAL_REPO/frontend/package-lock.json' '$BASE_DIR/package-lock.json'
    cd '$BASE_DIR'
    npm install
"

# --- Per-instance: build, migrate, restart ---
FAILED_INSTANCES=()
for instance in "${TARGETS[@]}"; do
    instance_dir="$INSTANCES_DIR/$instance"
    inst_user="$(instance_user "$instance")"

    log "--- Processing instance: $instance ---"

    # Build frontend
    log "  Building frontend..."
    sudo -u "$inst_user" bash -c "
        cd '$instance_dir/frontend'
        npm run build
    "

    # Collect static files + run migrations
    log "  Running migrate..."
    if "$SCRIPT_DIR/dw-run.sh" "$instance" python manage.py migrate --no-input; then
        log "  Django commands complete for $instance"
    else
        log "  ERROR: Django commands failed for $instance"
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
    log "  WARNING: Failed instances: ${FAILED_INSTANCES[*]}"
fi
log "=========================================="
