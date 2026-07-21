#!/bin/bash
# Shared constants and helpers for server scripts.
# shellcheck disable=SC2034  # constants below are consumed by scripts that source this library

DOMAIN="docketworks.site"
BASE_DIR="/opt/docketworks"
INSTANCES_DIR="$BASE_DIR/instances"
CONFIG_DIR="$BASE_DIR/config"
SHARED_PLAYWRIGHT_BROWSERS="$BASE_DIR/.playwright-browsers"
LOCAL_REPO="$BASE_DIR/repo"
RELEASES_DIR="$BASE_DIR/releases"
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

# Guard: a prod instance only ever runs origin/production (ADR 0029). A
# non-production ref on a *-prod instance is almost always an accident (e.g. a
# --ref copied from a UAT command), so refuse unless explicitly acknowledged:
# interactively with a y/N prompt, or non-interactively with allow="true"/"1".
# The default ref and all non-prod instances (uat/demo/dev) pass through.
require_production_ref_or_ack() {
    local instance="$1"
    local ref="$2"
    local allow="${3:-false}"

    if [[ "$ref" == "origin/production" ]]; then
        return 0
    fi
    if [[ "$instance" != *-prod ]]; then
        return 0
    fi

    if [[ "$allow" == "true" || "$allow" == "1" ]]; then
        echo "WARNING: deploying non-production ref '$ref' to PROD instance '$instance' (--allow-prod-ref)." >&2
        return 0
    fi

    if [[ -t 0 ]]; then
        echo "Refusing non-production ref '$ref' on PROD instance '$instance'." >&2
        local reply
        read -r -p "  Deploy it to prod anyway? [y/N] " reply
        if [[ "$reply" == "y" || "$reply" == "Y" ]]; then
            return 0
        fi
    fi

    echo "ERROR: prod instances run origin/production (ADR 0029)." >&2
    echo "  Pass --allow-prod-ref to override non-interactively." >&2
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

instance_backup_dir() {
    local instance="$1"
    echo "$INSTANCES_DIR/$instance/backups"
}

ensure_instance_backup_dir() {
    local instance="$1"
    local instance_user="$2"
    local backup_dir

    backup_dir="$(instance_backup_dir "$instance")"
    mkdir -p "$backup_dir"
    chown "$instance_user:$instance_user" "$backup_dir"
    chmod 700 "$backup_dir"
}

node_major_from_nvmrc() {
    local nvmrc_file="$1"
    local major
    major="$(sed -nE 's/^[[:space:]]*v?([0-9]+).*/\1/p' "$nvmrc_file" | head -n 1)"
    if [[ -z "$major" ]]; then
        echo "ERROR: Could not parse Node major from $nvmrc_file" >&2
        exit 1
    fi
    printf "%s\n" "$major"
}

read_env_value() {
    local env_file="$1"
    local var_name="$2"
    local line value

    if [[ ! -f "$env_file" ]]; then
        printf ""
        return
    fi
    if [[ ! "$var_name" =~ ^[A-Z0-9_]+$ ]]; then
        echo "ERROR: Invalid env var name requested: $var_name" >&2
        exit 1
    fi

    line="$(grep -m1 -E "^${var_name}=" "$env_file" || true)"
    if [[ -z "$line" ]]; then
        printf ""
        return
    fi

    value="${line#*=}"
    if [[ "$value" == \"*\" && "$value" == *\" ]]; then
        value="${value:1:${#value}-2}"
    elif [[ "$value" == \'*\' && "$value" == *\' ]]; then
        value="${value:1:${#value}-2}"
    fi
    printf "%s" "$value"
}

ensure_config_dir() {
    if [[ -L "$CONFIG_DIR" ]]; then
        echo "ERROR: Credentials directory must not be a symlink: $CONFIG_DIR" >&2
        exit 1
    fi
    mkdir -p "$CONFIG_DIR"
    chown root:root "$CONFIG_DIR"
    chmod 755 "$CONFIG_DIR"
}

require_root_owned_credentials_file() {
    local creds_file="$1"
    local config_dir
    config_dir="$(dirname "$creds_file")"

    if [[ ! -d "$config_dir" ]]; then
        echo "ERROR: Credentials directory not found: $config_dir" >&2
        exit 1
    fi
    if [[ -L "$config_dir" ]]; then
        echo "ERROR: Credentials directory must not be a symlink: $config_dir" >&2
        exit 1
    fi
    if [[ "$(stat -c '%u:%g:%a' "$config_dir")" != "0:0:755" ]]; then
        echo "ERROR: Credentials directory must be root:root mode 755: $config_dir" >&2
        echo "  Fix after auditing contents:" >&2
        echo "    sudo chown root:root $config_dir && sudo chmod 755 $config_dir" >&2
        exit 1
    fi

    if [[ ! -f "$creds_file" ]]; then
        echo "ERROR: Credentials file not found: $creds_file" >&2
        exit 1
    fi
    if [[ -L "$creds_file" ]]; then
        echo "ERROR: Credentials file must not be a symlink: $creds_file" >&2
        exit 1
    fi
    if [[ "$(stat -c '%u:%g:%a' "$creds_file")" != "0:0:600" ]]; then
        echo "ERROR: Credentials file must be root:root mode 600: $creds_file" >&2
        echo "  Fix after auditing contents:" >&2
        echo "    sudo chown root:root $creds_file && sudo chmod 600 $creds_file" >&2
        exit 1
    fi
}

write_instance_rclone_config() {
    local instance="$1"
    local instance_user="$2"
    local root_folder_id="${3:-}"
    local team_drive_id="${4:-}"
    local config_path

    config_path="$(instance_rclone_config "$instance")"
    mkdir -p "$RCLONE_CONFIG_DIR"
    chmod 755 "$RCLONE_CONFIG_DIR"
    {
        echo "[gdrive]"
        echo "type = drive"
        echo "scope = drive"
        echo "service_account_file = $INSTANCES_DIR/$instance/gcp-credentials.json"
        if [[ -n "$team_drive_id" ]]; then
            echo "team_drive = $team_drive_id"
        fi
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

    sed \
        -e "s|__INSTANCE__|$instance|g" \
        -e "s|__INSTANCE_USER__|$instance_user|g" \
        -e "s|__RCLONE_CONFIG__|$(instance_rclone_config "$instance")|g" \
        "$template_dir/backup-files-instance.service.template" \
        > "/etc/systemd/system/backup-files-$instance.service"

    sed \
        -e "s|__INSTANCE__|$instance|g" \
        "$template_dir/backup-files-instance.timer.template" \
        > "/etc/systemd/system/backup-files-$instance.timer"
}
