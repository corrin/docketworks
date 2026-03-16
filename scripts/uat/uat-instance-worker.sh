#!/bin/bash
set -euo pipefail

# Worker script for UAT instance setup — runs as docketworks user (no sudo).
# Called by uat-create-instance.sh after root-only operations are complete.
# Usage: uat-instance-worker.sh <instance-name> <branch> <seed: true|false>

INSTANCE="$1"
BRANCH="$2"
SEED="$3"

BASE_DIR="/opt/docketworks"
INSTANCES_DIR="$BASE_DIR/instances"
INSTANCE_DIR="$INSTANCES_DIR/$INSTANCE"
CODE_DIR="$INSTANCE_DIR/code"
SHARED_VENV="$BASE_DIR/.venv"
SHARED_NODE_MODULES="$BASE_DIR/node_modules"
REPO_URL="git@github.com:corrin/docketworks.git"
SETUP_LOG="/var/log/docketworks-setup.log"

# Fix PATH for pkg-config and other tools
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/opt/docketworks/.local/bin"

log() {
    local msg="[$(date '+%Y-%m-%d %H:%M:%S')] $*"
    echo "$msg" | tee -a "$SETUP_LOG"
}

# --- Clone or update codebase ---
if [[ -d "$CODE_DIR/.git" ]]; then
    log "Code already cloned — pulling latest on branch $BRANCH..."
    cd "$CODE_DIR"
    git fetch origin
    git checkout "$BRANCH"
    git pull --ff-only
else
    log "Cloning codebase to $CODE_DIR (branch: $BRANCH)..."
    git clone --branch "$BRANCH" "$REPO_URL" "$CODE_DIR"
fi

# --- Shared venv (create if first instance) ---
if [[ ! -d "$SHARED_VENV" ]]; then
    log "Creating shared Python venv at $SHARED_VENV..."
    python3.12 -m venv "$SHARED_VENV"
    source "$SHARED_VENV/bin/activate"
    pip install --upgrade pip
    cd "$CODE_DIR"
    poetry install --no-interaction
else
    log "Shared venv already exists at $SHARED_VENV."
fi

# Symlink .venv into code/
if [[ -L "$CODE_DIR/.venv" ]]; then
    log "  .venv symlink already exists."
elif [[ -d "$CODE_DIR/.venv" ]]; then
    log "  ERROR: $CODE_DIR/.venv is a real directory, not a symlink. Remove it first."
    exit 1
else
    ln -s "$SHARED_VENV" "$CODE_DIR/.venv"
    log "  Symlinked $CODE_DIR/.venv → $SHARED_VENV"
fi

# --- Shared node_modules (create if first instance) ---
if [[ ! -d "$SHARED_NODE_MODULES" ]]; then
    log "Installing shared node_modules at $SHARED_NODE_MODULES..."
    cd "$CODE_DIR/frontend"
    npm install --prefix "$BASE_DIR" --install-links
else
    log "Shared node_modules already exists at $SHARED_NODE_MODULES."
fi

# Symlink node_modules into code/frontend/
if [[ -L "$CODE_DIR/frontend/node_modules" ]]; then
    log "  node_modules symlink already exists."
elif [[ -d "$CODE_DIR/frontend/node_modules" ]]; then
    log "  ERROR: $CODE_DIR/frontend/node_modules is a real directory, not a symlink. Remove it first."
    exit 1
else
    ln -s "$SHARED_NODE_MODULES" "$CODE_DIR/frontend/node_modules"
    log "  Symlinked $CODE_DIR/frontend/node_modules → $SHARED_NODE_MODULES"
fi

# --- Build frontend ---
log "Building frontend for instance $INSTANCE..."
cd "$CODE_DIR/frontend"
npm run build

# --- Load .env for Django commands ---
cd "$CODE_DIR"
source .venv/bin/activate
set -a
source "$INSTANCE_DIR/.env"
set +a

# --- Collect static files ---
log "Collecting static files for instance $INSTANCE..."
python manage.py collectstatic --no-input

# --- Run migrations ---
log "Running migrations..."
python manage.py migrate --no-input

# --- Optionally seed data ---
if [[ "$SEED" == "true" ]]; then
    log "Loading demo fixtures..."
    python manage.py loaddata demo_fixtures
fi

log "Worker script completed successfully for instance $INSTANCE."
