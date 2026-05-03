#!/bin/bash
set -euo pipefail

# Deploy one or all instances.
# Usage: deploy.sh <name> [--no-backup] [--allow-dirty]
#        deploy.sh --all  [--no-backup] [--allow-dirty]
#
# Flags:
#   --no-backup     Skip the pre-deploy pg_dump. Default: take a backup.
#   --allow-dirty   Proceed even if an instance's working tree has uncommitted
#                   changes. Default: abort (a dirty tree makes the hash we
#                   stamp on the backup a lie about what code will restore).
#
# DR mode: if an instance directory contains a .dr-mode marker file, this
# script still runs migrations, builds the frontend, and re-renders unit and
# nginx configs — but it does NOT enable or restart gunicorn / celery-worker.
# This is the "cold standby" posture: deploys keep the instance current
# without it ever serving traffic or hitting Xero with shared live tokens.
#
# Steps:
#   1. Per-instance: clean-tree check, pg_dump, git pull
#   2. Update shared deps (poetry install, npm install)
#   3. Per-instance: npm run build, migrate, restart

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/common.sh"

if [[ $EUID -ne 0 ]]; then
    echo "ERROR: This script must be run as root (use sudo)."
    exit 1
fi

# sudo inherits the caller's cwd. If the operator ran this from /home/ubuntu
# (mode 750 ubuntu:ubuntu), the docketworks/instance users sudo'd to below
# can't read it, and python/poetry/npm startup hits getcwd EACCES and dies —
# silently aborting the deploy before per-instance work runs. Anchor cwd to /
# so every sudo -u below (and the server-setup.sh invocation) inherits
# something universally readable.
cd /

USAGE="Usage: $0 <instance-name> [--no-backup] [--allow-dirty]
       $0 --all          [--no-backup] [--allow-dirty]"

if ! parsed=$(getopt -o '' --long all,no-backup,allow-dirty -n "$(basename "$0")" -- "$@"); then
    echo "$USAGE" >&2
    exit 1
fi
eval set -- "$parsed"

DO_BACKUP=1
ALLOW_DIRTY=0
DEPLOY_ALL=0
while true; do
    case "$1" in
        --no-backup)   DO_BACKUP=0;   shift ;;
        --allow-dirty) ALLOW_DIRTY=1; shift ;;
        --all)         DEPLOY_ALL=1;  shift ;;
        --)            shift; break ;;
    esac
done

# --- Determine which instances to deploy ---
TARGETS=()
if [[ $DEPLOY_ALL -eq 1 ]]; then
    if [[ $# -gt 0 ]]; then
        echo "ERROR: Cannot pass an instance name together with --all" >&2
        echo "$USAGE" >&2
        exit 1
    fi
    for instance_dir in "$INSTANCES_DIR"/*/; do
        [[ -d "$instance_dir" ]] || continue
        if [[ -f "$instance_dir/.env" && -d "$instance_dir/.git" ]]; then
            TARGETS+=("$(basename "$instance_dir")")
        fi
    done
    if [[ ${#TARGETS[@]} -eq 0 ]]; then
        echo "ERROR: No instances found in $INSTANCES_DIR" >&2
        exit 1
    fi
else
    if [[ $# -ne 1 ]]; then
        echo "$USAGE" >&2
        exit 1
    fi
    TARGETS=("$1")
    local_dir="$INSTANCES_DIR/$1"
    if [[ ! -d "$local_dir" ]]; then
        echo "ERROR: Instance directory $local_dir does not exist." >&2
        exit 1
    fi
    if [[ ! -f "$local_dir/.env" ]]; then
        echo "ERROR: No .env file found at $local_dir/.env" >&2
        exit 1
    fi
    if [[ ! -d "$local_dir/.git" ]]; then
        echo "ERROR: No git repo found at $local_dir" >&2
        exit 1
    fi
fi

log "=========================================="
log "Deploying: ${TARGETS[*]}"
log "=========================================="

# --- Update local repo from GitHub ---
log "Pulling latest from GitHub into local repo..."
sudo -u docketworks git -C "$LOCAL_REPO" pull --ff-only

# --- Converge system-level dependencies (only when inputs change) ---
# server-setup.sh is idempotent, but its no-op path still scans every dpkg
# and `command -v` guard. ~80% of PRs touch nothing it reads. Hash the
# files server-setup.sh actually consumes (itself, the certbot hooks it
# copies, and the logrotate template); skip the re-run when the hash
# matches the last successful run. Adding a new file to server-setup.sh's
# inputs requires adding it here too — review-visible because it lives
# next to the bash invocation.
SERVER_SETUP_INPUTS=(
    "$SCRIPT_DIR/server-setup.sh"
    "$SCRIPT_DIR/certbot-dreamhost-auth.sh"
    "$SCRIPT_DIR/certbot-dreamhost-cleanup.sh"
    "$SCRIPT_DIR/templates/logrotate-docketworks.conf"
)
SERVER_SETUP_HASH="$(sha256sum "${SERVER_SETUP_INPUTS[@]}" | sha256sum | awk '{print $1}')"
SERVER_SETUP_STAMP="/opt/docketworks/.server-setup-hash"
if [[ -f "$SERVER_SETUP_STAMP" && "$(cat "$SERVER_SETUP_STAMP")" == "$SERVER_SETUP_HASH" ]]; then
    log "server-setup.sh inputs unchanged since last successful run; skipping convergence."
else
    log "Converging system-level dependencies via server-setup.sh..."
    if ! bash "$SCRIPT_DIR/server-setup.sh"; then
        log "  ERROR: server-setup.sh failed; not stamping."
        exit 1
    fi
    # Stamp only after successful return — never on failure or partial run.
    echo "$SERVER_SETUP_HASH" > "$SERVER_SETUP_STAMP"
    log "  Stamped $SERVER_SETUP_STAMP with current input hash."
fi

# --- Per-instance prepare: clean-tree check, pre-deploy backup, git pull ---
for instance in "${TARGETS[@]}"; do
    inst_dir="$INSTANCES_DIR/$instance"
    inst_user="$(instance_user "$instance")"

    # Clean-tree check. A dirty tree means the commit hash we'd stamp on
    # the backup doesn't fully describe the code that produced the data,
    # so a later `git checkout <hash>` would silently drop the uncommitted
    # bit. UAT/prod instances should never be dirty; dirty = something
    # needs investigation.
    tree_dirty=0
    if ! sudo -u "$inst_user" git -C "$inst_dir" diff --quiet --ignore-submodules HEAD --; then
        tree_dirty=1
    elif [[ -n "$(sudo -u "$inst_user" git -C "$inst_dir" status --porcelain)" ]]; then
        tree_dirty=1
    fi
    if [[ $tree_dirty -eq 1 ]]; then
        if [[ $ALLOW_DIRTY -eq 1 ]]; then
            log "WARNING: $instance has a dirty working tree (--allow-dirty set, proceeding)"
        else
            log "ERROR: $instance has a dirty working tree. Refusing to deploy."
            log "  Investigate with: sudo -u $inst_user git -C $inst_dir status"
            log "  To override: re-run with --allow-dirty"
            exit 1
        fi
    fi

    if [[ $DO_BACKUP -eq 1 ]]; then
        log "Backing up DB for $instance (pre-deploy)..."
        "$SCRIPT_DIR/../predeploy_backup.sh" "$instance"
    else
        log "Skipping pre-deploy backup for $instance (--no-backup)"
    fi

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

    # Re-render the celery-worker unit on every deploy. Idempotent: systemd's
    # daemon-reload only re-reads files that changed, and `enable` is a no-op
    # on an already-enabled unit. Always-rendering means template edits
    # (flags, environment, hostname) reach existing instances without manual
    # intervention — the previous "render once" guard meant a flag added in
    # this PR would silently never apply on UAT/prod.
    log "  Rendering celery-worker-$instance unit"
    sed \
        -e "s|__INSTANCE__|$instance|g" \
        -e "s|__INSTANCE_USER__|$inst_user|g" \
        "$SCRIPT_DIR/templates/celery-worker-instance.service.template" \
        > "/etc/systemd/system/celery-worker-$instance.service"
    systemctl daemon-reload

    # DR-mode short-circuit. The marker means this instance is a cold standby:
    # render unit files (so a future "go live" picks up template changes), but
    # never enable or start the services that talk to live external systems.
    if [[ -f "$instance_dir/.dr-mode" ]]; then
        log "  DR mode (.dr-mode present): skipping enable/restart of celery-worker-$instance and gunicorn-$instance"
    else
        systemctl enable "celery-worker-$instance"

        # Restart celery-worker BEFORE gunicorn. If gunicorn restarts first it
        # starts dispatching new task names while the worker still has stale
        # code; the old worker silently ack-discards messages it doesn't know
        # (Celery's default behaviour) and webhook events are lost without a
        # trace. Worker-first means new task names are always registered before
        # any new dispatch can land.
        log "  Restarting celery-worker-$instance"
        systemctl restart "celery-worker-$instance"

        # Restart gunicorn
        if systemctl is-enabled "gunicorn-$instance" &>/dev/null; then
            log "  Restarting gunicorn-$instance"
            systemctl restart "gunicorn-$instance"
        fi
    fi

    # Re-render nginx config from template. The rendered config is written once
    # at instance creation (instance.sh), so template edits only reach live
    # servers if we re-render on each deploy. FQDN and cert domain are pulled
    # back out of the existing rendered config — we need whatever was true at
    # creation time, and parsing the live config is the one source of truth
    # we know matches the cert actually in use.
    existing_conf="/etc/nginx/sites-available/docketworks-$instance"
    if [[ ! -f "$existing_conf" ]]; then
        log "  ERROR: No existing nginx config at $existing_conf. Run instance.sh first."
        FAILED_INSTANCES+=("$instance")
        continue
    fi
    # Keep internal spaces so multi-name server_name directives survive re-rendering.
    FQDN=$(grep -oP 'server_name \K[^;]+' "$existing_conf" | head -1 | awk '{$1=$1; print}')
    CERT_DOMAIN=$(grep -oP 'ssl_certificate /etc/letsencrypt/live/\K[^/]+' "$existing_conf" | head -1)
    if [[ -z "$FQDN" || -z "$CERT_DOMAIN" ]]; then
        log "  ERROR: Could not extract FQDN/CERT_DOMAIN from $existing_conf"
        FAILED_INSTANCES+=("$instance")
        continue
    fi
    log "  Re-rendering nginx config (FQDN=$FQDN, CERT_DOMAIN=$CERT_DOMAIN)"
    sed \
        -e "s|__INSTANCE__|$instance|g" \
        -e "s|__FQDN__|$FQDN|g" \
        -e "s|__CERT_DOMAIN__|$CERT_DOMAIN|g" \
        "$SCRIPT_DIR/templates/nginx-instance.conf.template" \
        > "$existing_conf"
done

# --- Reload nginx once if any configs were rewritten ---
if nginx -t 2>&1; then
    log "Reloading nginx..."
    systemctl reload nginx
else
    log "ERROR: nginx -t failed. Configs written but NOT reloaded."
    log "  Fix the config error and run: systemctl reload nginx"
    exit 1
fi

# --- Summary ---
log "=========================================="
log "Deploy complete"
if [[ ${#FAILED_INSTANCES[@]} -gt 0 ]]; then
    log "  WARNING: Failed instances: ${FAILED_INSTANCES[*]}"
fi
log "=========================================="
