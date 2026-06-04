#!/bin/bash
# Shared constants and helpers for server scripts.

DOMAIN="docketworks.site"
BASE_DIR="/opt/docketworks"
INSTANCES_DIR="$BASE_DIR/instances"
CONFIG_DIR="$BASE_DIR/config"
SHARED_VENV="$BASE_DIR/.venv"
SHARED_PLAYWRIGHT_BROWSERS="$BASE_DIR/.playwright-browsers"
LOCAL_REPO="$BASE_DIR/repo"
REMOTE_REPO_URL="https://github.com/corrin/docketworks.git"
RCLONE_CONFIG_DIR="$CONFIG_DIR/rclone"

VALID_ENVS="dev uat staging prod demo"

# Per-instance disk quotas (requires filesystem quotas enabled on /opt or /)
QUOTA_SOFT="2G"
QUOTA_HARD="5G"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a /var/log/docketworks-setup.log
}

validate_env() {
    local env="$1"
    for valid in $VALID_ENVS; do
        [[ "$env" == "$valid" ]] && return 0
    done
    echo "ERROR: Invalid environment '$env'. Must be one of: $VALID_ENVS"
    exit 1
}

# Returns the OS user name for an instance: "msm-prod" -> "dw_msm_prod".
# Matches the DB role name (see templates/env-instance.template DB_USER)
# so Postgres peer auth via socket is possible and scripts only need one
# string for both the Linux account and the database role.
instance_user() {
    local instance="$1"
    echo "dw_${instance//-/_}"
}

instance_rclone_config() {
    local instance="$1"
    echo "$RCLONE_CONFIG_DIR/$instance.conf"
}

write_instance_rclone_config() {
    local instance="$1"
    local instance_user="$2"
    local root_folder_id="${3:-}"
    local config_path

    config_path="$(instance_rclone_config "$instance")"
    mkdir -p "$RCLONE_CONFIG_DIR"
    chmod 755 "$RCLONE_CONFIG_DIR"
    {
        echo "[gdrive]"
        echo "type = drive"
        echo "scope = drive"
        echo "service_account_file = $INSTANCES_DIR/$instance/gcp-credentials.json"
        if [[ -n "$root_folder_id" ]]; then
            echo "root_folder_id = $root_folder_id"
        fi
    } > "$config_path"
    chown "$instance_user:$instance_user" "$config_path"
    chmod 600 "$config_path"
}

render_backup_units() {
    local instance="$1"
    local instance_user="$2"
    local template_dir="${3:-$SCRIPT_DIR/templates}"

    sed \
        -e "s|__INSTANCE__|$instance|g" \
        -e "s|__INSTANCE_USER__|$instance_user|g" \
        -e "s|__RCLONE_CONFIG__|$(instance_rclone_config "$instance")|g" \
        "$template_dir/backup-db-instance.service.template" \
        > "/etc/systemd/system/backup-db-$instance.service"

    sed \
        -e "s|__INSTANCE__|$instance|g" \
        "$template_dir/backup-db-instance.timer.template" \
        > "/etc/systemd/system/backup-db-$instance.timer"
}
