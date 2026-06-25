#!/bin/bash
set -euo pipefail

# Deploy one or all instances through a shared immutable release directory.
# Usage: deploy.sh <name> [--ref <branch|tag|sha>] [--no-backup] [--allow-dirty]
#        deploy.sh --all  [--ref <branch|tag|sha>] [--no-backup] [--allow-dirty]
#        deploy.sh --cleanup-releases
#
# Normal operator path after a PR is merged:
#   sudo scripts/server/deploy.sh <instance>
#
# That command fetches GitHub, resolves origin/main to a SHA, builds
# /opt/docketworks/releases/<sha> if missing, then switches only the requested
# instance to that release.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SELF="$SCRIPT_DIR/$(basename "$0")"
ORIG_ARGS=("$@")
source "$SCRIPT_DIR/common.sh"
source "$SCRIPT_DIR/release-utils.sh"

if [[ $EUID -ne 0 ]]; then
    echo "ERROR: This script must be run as root (use sudo)."
    exit 1
fi

cd /

USAGE="Usage: $0 <instance-name> [--ref <branch|tag|sha>] [--no-backup] [--allow-dirty]
       $0 --all          [--ref <branch|tag|sha>] [--no-backup] [--allow-dirty]
       $0 --cleanup-releases"

if ! parsed=$(getopt -o '' --long all,no-backup,allow-dirty,cleanup-releases,ref: -n "$(basename "$0")" -- "$@"); then
    echo "$USAGE" >&2
    exit 1
fi
eval set -- "$parsed"

DO_BACKUP=1
ALLOW_DIRTY=0
DEPLOY_ALL=0
DO_CLEANUP_RELEASES=0
TARGET_REF="origin/main"
while true; do
    case "$1" in
        --no-backup)   DO_BACKUP=0;      shift ;;
        --allow-dirty) ALLOW_DIRTY=1;    shift ;;
        --cleanup-releases) DO_CLEANUP_RELEASES=1; shift ;;
        --all)         DEPLOY_ALL=1;     shift ;;
        --ref)         TARGET_REF="$2";  shift 2 ;;
        --)            shift; break ;;
    esac
done

exec 9>"$BASE_DIR/.deploy.lock"
if ! flock -n 9; then
    echo "ERROR: another deploy is already running." >&2
    exit 1
fi

if [[ $DO_CLEANUP_RELEASES -eq 1 ]]; then
    if [[ $# -gt 0 || $DEPLOY_ALL -eq 1 || $DO_BACKUP -eq 0 || $ALLOW_DIRTY -eq 1 || "$TARGET_REF" != "origin/main" ]]; then
        echo "ERROR: --cleanup-releases cannot be combined with deploy targets or deploy flags." >&2
        echo "$USAGE" >&2
        exit 1
    fi
    cleanup_incomplete_releases
    cleanup_unreferenced_releases
    exit 0
fi

validate_instance() {
    local instance="$1"
    local local_dir="$INSTANCES_DIR/$instance"

    if [[ ! -d "$local_dir" ]]; then
        echo "ERROR: Instance directory $local_dir does not exist." >&2
        exit 1
    fi
    if [[ ! -f "$local_dir/.env" ]]; then
        echo "ERROR: No .env file found at $local_dir/.env" >&2
        exit 1
    fi
    if [[ ! -L "$local_dir/current" && ! -d "$local_dir/.git" ]]; then
        echo "ERROR: $local_dir has neither current release link nor legacy git checkout." >&2
        exit 1
    fi
}

render_runtime_units() {
    local instance="$1"
    local inst_user="$2"

    log "  Rendering celery-worker-$instance unit"
    sed \
        -e "s|__INSTANCE__|$instance|g" \
        -e "s|__INSTANCE_USER__|$inst_user|g" \
        "$SCRIPT_DIR/templates/celery-worker-instance.service.template" \
        > "/etc/systemd/system/celery-worker-$instance.service"

    log "  Rendering celery-beat-$instance unit"
    sed \
        -e "s|__INSTANCE__|$instance|g" \
        -e "s|__INSTANCE_USER__|$inst_user|g" \
        "$SCRIPT_DIR/templates/celery-beat-instance.service.template" \
        > "/etc/systemd/system/celery-beat-$instance.service"

    log "  Rendering gunicorn-$instance unit"
    sed \
        -e "s|__INSTANCE__|$instance|g" \
        -e "s|__INSTANCE_USER__|$inst_user|g" \
        "$SCRIPT_DIR/templates/gunicorn-instance.service.template" \
        > "/etc/systemd/system/gunicorn-$instance.service"

    systemctl daemon-reload
}

render_backup_timer() {
    local instance="$1"
    local inst_user="$2"
    local backup_root_folder_id=""
    local creds_file="$CONFIG_DIR/$instance.credentials.env"

    if [[ -f "$creds_file" ]]; then
        require_root_owned_credentials_file "$creds_file"
        backup_root_folder_id="$(read_env_value "$creds_file" BACKUP_GDRIVE_ROOT_FOLDER_ID)"
    fi
    log "  Rendering backup-db-$instance units"
    write_instance_rclone_config "$instance" "$inst_user" "$backup_root_folder_id"
    render_backup_units "$instance" "$inst_user" "$SCRIPT_DIR/templates"
    systemctl daemon-reload
    systemctl enable --now "backup-db-$instance.timer"
}

render_nginx_config() {
    local instance="$1"
    local existing_conf="/etc/nginx/sites-available/docketworks-$instance"
    local fqdn cert_domain

    if [[ ! -f "$existing_conf" ]]; then
        log "  ERROR: No existing nginx config at $existing_conf. Run instance.sh first."
        return 1
    fi

    fqdn=$(grep -oP 'server_name \K[^;]+' "$existing_conf" | head -1 | awk '{$1=$1; print}' || true)
    cert_domain=$(grep -oP 'ssl_certificate /etc/letsencrypt/live/\K[^/]+' "$existing_conf" | head -1 || true)
    if [[ -z "$fqdn" || -z "$cert_domain" ]]; then
        log "  ERROR: Could not extract FQDN/CERT_DOMAIN from $existing_conf"
        return 1
    fi

    log "  Re-rendering nginx config (FQDN=$fqdn, CERT_DOMAIN=$cert_domain)"
    sed \
        -e "s|__INSTANCE__|$instance|g" \
        -e "s|__FQDN__|$fqdn|g" \
        -e "s|__CERT_DOMAIN__|$cert_domain|g" \
        "$SCRIPT_DIR/templates/nginx-instance.conf.template" \
        > "$existing_conf"
}

restart_instance_units() {
    local instance="$1"
    local instance_dir="$INSTANCES_DIR/$instance"

    if [[ -f "$instance_dir/.dr-mode" ]]; then
        log "  DR mode (.dr-mode present): skipping enable/restart of celery-worker-$instance, celery-beat-$instance, and gunicorn-$instance"
        return 0
    fi

    systemctl enable "celery-worker-$instance"
    log "  Restarting celery-worker-$instance"
    systemctl restart "celery-worker-$instance"

    systemctl enable "celery-beat-$instance"
    log "  Restarting celery-beat-$instance"
    systemctl restart "celery-beat-$instance"

    systemctl enable "gunicorn-$instance"
    log "  Restarting gunicorn-$instance"
    systemctl restart "gunicorn-$instance"
}

stop_instance_units() {
    local instance="$1"

    log "  Stopping celery-beat-$instance"
    systemctl stop "celery-beat-$instance" 2>/dev/null || true

    log "  Stopping celery-worker-$instance"
    systemctl stop "celery-worker-$instance" 2>/dev/null || true

    log "  Stopping gunicorn-$instance"
    systemctl stop "gunicorn-$instance" 2>/dev/null || true
}

remove_legacy_scheduler_unit() {
    local instance="$1"

    if [[ -f "/etc/systemd/system/scheduler-$instance.service" ]]; then
        log "  Removing legacy scheduler-$instance unit (replaced by celery-beat)"
        systemctl stop "scheduler-$instance" 2>/dev/null || true
        systemctl disable "scheduler-$instance" 2>/dev/null || true
        rm -f "/etc/systemd/system/scheduler-$instance.service"
        systemctl daemon-reload
    fi
}

# --- Determine targets ---
TARGETS=()
if [[ $DEPLOY_ALL -eq 1 ]]; then
    if [[ $# -gt 0 ]]; then
        echo "ERROR: Cannot pass an instance name together with --all" >&2
        echo "$USAGE" >&2
        exit 1
    fi
    for instance_dir in "$INSTANCES_DIR"/*/; do
        [[ -d "$instance_dir" ]] || continue
        if [[ -f "$instance_dir/.env" ]]; then
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
fi

for instance in "${TARGETS[@]}"; do
    validate_instance "$instance"
done

log "=========================================="
log "Deploying: ${TARGETS[*]}"
log "Target ref: $TARGET_REF"
log "=========================================="

# --- Update local repo from GitHub ---
log "Pulling latest from GitHub into local repo..."
SELF_HASH_BEFORE="$(sha256sum "$SELF" | awk '{print $1}')"
sudo -u docketworks git -C "$LOCAL_REPO" pull --ff-only

SELF_HASH_AFTER="$(sha256sum "$SELF" | awk '{print $1}')"
if [[ "$SELF_HASH_BEFORE" != "$SELF_HASH_AFTER" && -z "${DOCKETWORKS_DEPLOY_REEXECED:-}" ]]; then
    log "deploy.sh updated by git pull — re-execing with new version"
    DOCKETWORKS_DEPLOY_REEXECED=1 exec "$SELF" "${ORIG_ARGS[@]}"
fi

fetch_local_repo
TARGET_SHA="$(resolve_release_ref "$TARGET_REF")"
TARGET_SHORT="${TARGET_SHA:0:12}"
log "Resolved $TARGET_REF to $TARGET_SHA"

# --- Converge system-level dependencies (only when inputs change) ---
SERVER_SETUP_INPUTS=(
    "$SCRIPT_DIR/server-setup.sh"
    "$SCRIPT_DIR/certbot-dreamhost-auth.sh"
    "$SCRIPT_DIR/certbot-dreamhost-cleanup.sh"
    "$SCRIPT_DIR/templates/logrotate-docketworks.conf"
    "$SCRIPT_DIR/templates/nginx-instance.conf.template"
    "$SCRIPT_DIR/templates/backup-db-instance.service.template"
    "$SCRIPT_DIR/templates/backup-db-instance.timer.template"
    "$SCRIPT_DIR/templates/gunicorn-instance.service.template"
    "$SCRIPT_DIR/templates/celery-worker-instance.service.template"
    "$SCRIPT_DIR/templates/celery-beat-instance.service.template"
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
    echo "$SERVER_SETUP_HASH" > "$SERVER_SETUP_STAMP"
    log "  Stamped $SERVER_SETUP_STAMP with current input hash."
fi

cleanup_incomplete_releases
ensure_release "$TARGET_SHA"

FAILED_INSTANCES=()
for instance in "${TARGETS[@]}"; do
    instance_dir="$INSTANCES_DIR/$instance"
    inst_user="$(instance_user "$instance")"
    previous_sha="$(instance_current_sha "$instance")"

    log "--- Processing instance: $instance ---"
    log "  Previous SHA: ${previous_sha:-none}"
    log "  Target SHA:   $TARGET_SHA"

    if [[ -d "$instance_dir/.git" ]]; then
        tree_dirty=0
        if ! sudo -u "$inst_user" git -C "$instance_dir" diff --quiet --ignore-submodules HEAD --; then
            tree_dirty=1
        elif [[ -n "$(sudo -u "$inst_user" git -C "$instance_dir" status --porcelain)" ]]; then
            tree_dirty=1
        fi
        if [[ $tree_dirty -eq 1 ]]; then
            if [[ $ALLOW_DIRTY -eq 1 ]]; then
                log "  WARNING: $instance has a dirty legacy working tree (--allow-dirty set, proceeding)"
            else
                log "  ERROR: $instance has a dirty legacy working tree. Refusing to deploy."
                log "    Investigate with: sudo -u $inst_user git -C $instance_dir status"
                log "    To override: re-run with --allow-dirty"
                FAILED_INSTANCES+=("$instance")
                continue
            fi
        fi
    fi

    # Ensure the previous release is built so predeploy_rollback.sh has a target.
    # No-op on a normal deploy (its release is already complete); on a first
    # legacy->new cutover this builds the old SHA's release from the shared repo,
    # before anything destructive, so rollback works. Fatal if it cannot build —
    # don't cut over without a rollback target.
    if [[ -n "$previous_sha" ]]; then
        log "  Ensuring previous release ${previous_sha:0:12} is built (rollback target)..."
        ensure_release "$previous_sha"
    fi

    if [[ $DO_BACKUP -eq 1 ]]; then
        log "  Backing up DB for $instance (pre-deploy)..."
        "$SCRIPT_DIR/../predeploy_backup.sh" "$instance"
    else
        log "  Skipping pre-deploy backup for $instance (--no-backup)"
    fi

    stop_instance_units "$instance"

    switch_instance_release "$instance" "$TARGET_SHA"
    chown -h "$inst_user:$inst_user" "$instance_dir/current"

    log "  Running migrate..."
    if "$SCRIPT_DIR/dw-run.sh" "$instance" python manage.py migrate --no-input; then
        log "  Migration complete for $instance"
    else
        log "  ERROR: migrate failed for $instance — services remain stopped"
        log "  ERROR: DB may be partially migrated; code-only rollback is unsafe"
        log "  Inspect migrations:"
        log "    $SCRIPT_DIR/dw-run.sh $instance python manage.py showmigrations"
        if [[ -n "$previous_sha" ]]; then
            if [[ $DO_BACKUP -eq 1 ]]; then
                log "  Manual rollback, if required:"
                log "    sudo $SCRIPT_DIR/../predeploy_rollback.sh $instance ${previous_sha:0:12}"
            else
                log "  WARNING: --no-backup was used; no pre-deploy rollback backup was created"
            fi
        else
            log "  WARNING: no previous release SHA recorded for rollback guidance"
        fi
        FAILED_INSTANCES+=("$instance")
        continue
    fi

    remove_legacy_scheduler_unit "$instance"
    render_runtime_units "$instance" "$inst_user"
    render_backup_timer "$instance" "$inst_user"
    if ! render_nginx_config "$instance"; then
        FAILED_INSTANCES+=("$instance")
        continue
    fi

    restart_instance_units "$instance"

    {
        echo "PREVIOUS_SHA=$previous_sha"
        echo "CURRENT_SHA=$TARGET_SHA"
        echo "DEPLOYED_AT=$(date --iso-8601=seconds)"
    } > "$instance_dir/deploy-state.env"
    chown "$inst_user:$inst_user" "$instance_dir/deploy-state.env"
    chmod 600 "$instance_dir/deploy-state.env"

    compact_legacy_instance_checkout "$instance"
    log "  $instance now runs $TARGET_SHORT"
done

if nginx -t 2>&1; then
    log "Reloading nginx..."
    systemctl reload nginx
else
    log "ERROR: nginx -t failed. Configs written but NOT reloaded."
    log "  Fix the config error and run: systemctl reload nginx"
    exit 1
fi

if [[ ${#FAILED_INSTANCES[@]} -eq 0 ]]; then
    cleanup_unreferenced_releases "$TARGET_SHA"
else
    log "  Skipping release cleanup — failed instances may still need their previous release for rollback"
fi

log "=========================================="
log "Deploy complete"
if [[ ${#FAILED_INSTANCES[@]} -gt 0 ]]; then
    log "  WARNING: Failed instances: ${FAILED_INSTANCES[*]}"
    exit 1
fi
log "=========================================="
