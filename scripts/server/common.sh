#!/bin/bash
# Shared constants and helpers for server scripts.
# shellcheck disable=SC2034  # constants below are consumed by scripts that source this library

DOMAIN="docketworks.site"
BASE_DIR="/opt/docketworks"
INSTANCES_DIR="$BASE_DIR/instances"
CONFIG_DIR="$BASE_DIR/config"
LOCAL_REPO="$BASE_DIR/repo"
RELEASES_DIR="$BASE_DIR/releases"
REMOTE_REPO_URL="https://github.com/corrin/docketworks.git"
RCLONE_CONFIG_DIR="$CONFIG_DIR/rclone"
NGINX_SITES_AVAILABLE="/etc/nginx/sites-available"

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

# Guard: a prod instance normally tracks origin/production (ADR 0029). A
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

    echo "ERROR: prod instances normally track origin/production (ADR 0029)." >&2
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

# The single derivation of an instance's Postgres identifiers from
# <client>/<env> — assigns DB_NAME, DB_USER, SCRUB_DB_NAME, TEST_DB_USER
# and TEST_DB_NAME into the caller's scope (declare them local before
# calling). Create and destroy must agree on these five strings exactly,
# or destroy leaks what create provisioned; deriving them in one place is
# what keeps them in agreement.
#   DB_NAME/DB_USER    — the app database and its owning role (same string,
#                        matching the OS user for peer auth; see instance_user).
#   SCRUB_DB_NAME      — scratch database for manage.py backport_data_backup
#                        (and the demo export): created at instance creation so
#                        destroy's drop is never dead code and a production
#                        instance can produce scrubbed dumps without a manual
#                        provisioning step.
#   TEST_DB_USER       — separate role for pytest (config/settings_test.py
#                        connects as it). It carries CREATEDB rather than owning
#                        a pre-provisioned database: the suite runs under xdist
#                        (-n auto), so the runner itself creates and drops
#                        TEST_DB_NAME plus a _gwN clone per worker — a single
#                        owned database (v1's scheme) cannot serve parallel
#                        workers.
instance_db_names() {
    local client="$1"
    local env="$2"
    DB_NAME="dw_${client}_${env}"
    DB_USER="dw_${client}_${env}"
    SCRUB_DB_NAME="dw_${client}_${env}_scrub"
    TEST_DB_USER="dw_${client}_${env}_test"
    TEST_DB_NAME="$TEST_DB_USER"
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

# The hostnames an instance answers on: its canonical FQDN (.fqdn) first, then
# every alias (.aliases, one per line). instance.sh writes both files on every
# create and reconfigure, so a missing file is an instance that predates them
# and needs a reconfigure — not a case to default. The three readers this
# replaced each fell back to <instance>.docketworks.site, which is wrong for
# every --fqdn instance and was silently so.
instance_hostnames() {
    local instance="$1"
    local instance_dir="$INSTANCES_DIR/$instance"
    local file
    for file in .fqdn .aliases; do
        if [[ ! -f "$instance_dir/$file" ]]; then
            echo "ERROR: $instance_dir/$file is missing; run instance.sh reconfigure for $instance." >&2
            return 1
        fi
    done
    head -n1 "$instance_dir/.fqdn"
    sed '/^[[:space:]]*$/d' "$instance_dir/.aliases"
}

# The certbot live directory holding a hostname's certificate: a name under
# the fleet domain is on the wildcard, filed under the apex (server-setup.sh);
# any other name has a certificate of its own under its own name.
cert_live_dir() {
    local host="$1"
    if [[ "$host" == *".$DOMAIN" ]]; then
        echo "$DOMAIN"
    else
        echo "$host"
    fi
}

# One nginx site per instance, one server block per hostname: nginx binds one
# certificate per server block, and an alias off the fleet domain has its own.
# The unchanged template renders once per hostname into the same file, so the
# E2E fence include (ADR 0064), the auth rate limits and the access log reach
# every hostname by construction. instance.sh and deploy.sh both render here;
# deploy.sh used to scrape server_name out of the live file, which would now
# re-render only the first block.
render_instance_nginx() {
    local instance="$1"
    local hostnames host tmp_conf
    hostnames="$(instance_hostnames "$instance")" || return 1
    tmp_conf="$(mktemp)"
    for host in $hostnames; do
        sed \
            -e "s|__INSTANCE__|$instance|g" \
            -e "s|__FQDN__|$host|g" \
            -e "s|__CERT_DOMAIN__|$(cert_live_dir "$host")|g" \
            "$SCRIPT_DIR/templates/nginx-instance.conf.template" >> "$tmp_conf"
    done
    chmod 0644 "$tmp_conf"
    mv "$tmp_conf" "$NGINX_SITES_AVAILABLE/docketworks-$instance"
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

# The host's stock redis-server. It serves only the frozen v1 demo
# (docketworks_v1), whose env carries REDIS_HOST/REDIS_PORT for it; every v2
# instance runs its own redis-<instance> on a private port (ADR 0065). The
# first v2 instance on a box once shared this server with v1 and each worker
# consumed the other's tasks, which is why no instance is ever allocated it.
REDIS_SHARED_PORT=6379

# The Redis port an instance env binds to. A v2 env carries REDIS_URL; a v1
# env answers its REDIS_PORT, or the shared port when it names none. Anything
# else is a misconfigured neighbour and fails loudly rather than being
# skipped: skipping could hand out its (unknown) port twice. The URL is never
# echoed, because its userinfo is the password.
redis_port_of_env() {
    local env_file="$1"
    local url hostport port
    url="$(read_env_value "$env_file" REDIS_URL)"
    if [[ -z "$url" ]]; then
        if [[ -n "$(read_env_value "$env_file" REDIS_HOST)" ]]; then
            port="$(read_env_value "$env_file" REDIS_PORT)"
            printf '%s\n' "${port:-$REDIS_SHARED_PORT}"
            return 0
        fi
        echo "ERROR: $env_file carries neither REDIS_URL nor REDIS_HOST" >&2
        return 1
    fi
    hostport="${url##*@}"
    hostport="${hostport#redis://}"
    hostport="${hostport%%/*}"
    port="${hostport##*:}"
    if [[ "$hostport" != *:* || ! "$port" =~ ^[0-9]+$ ]]; then
        echo "ERROR: cannot parse a Redis port from REDIS_URL in $env_file" >&2
        return 1
    fi
    printf '%s\n' "$port"
}

# The password in a v2 env's REDIS_URL userinfo; empty when the URL carries
# none, which is the shape an instance had before it owned a Redis server.
redis_password_of_env() {
    local env_file="$1"
    local url userinfo
    url="$(read_env_value "$env_file" REDIS_URL)"
    if [[ "$url" != *@* ]]; then
        return 0
    fi
    userinfo="${url#redis://}"
    userinfo="${userinfo%%@*}"
    printf '%s' "${userinfo#*:}"
}

# The instance's Redis unit (ADR 0065). instance.sh installs it and deploy.sh
# re-renders it with the other units so a template change reaches every
# instance; the conf beside it, which carries the password, is instance.sh's
# alone, and deploy never restarts the unit.
render_redis_unit() {
    local instance="$1"
    local instance_user="$2"
    local template_dir="${3:-$SCRIPT_DIR/templates}"

    sed \
        -e "s|__INSTANCE__|$instance|g" \
        -e "s|__INSTANCE_USER__|$instance_user|g" \
        "$template_dir/redis-instance.service.template" \
        > "/etc/systemd/system/redis-$instance.service"
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

    # Fable: a service account has zero My-Drive quota, so without a shared drive
    # every upload 403s (storageQuotaExceeded) — sharing a personal folder to
    # the SA stopped working when Google changed quota attribution in 2021.
    # Prod ran that exact config, red every night, while a root cron with a
    # personal OAuth token did the real uploads. Refuse it at render time.
    if [[ -z "$team_drive_id" ]]; then
        echo "ERROR: BACKUP_GDRIVE_TEAM_DRIVE_ID is required: a service-account" >&2
        echo "remote without a shared drive cannot upload anything (no quota)." >&2
        return 1
    fi

    config_path="$(instance_rclone_config "$instance")"
    mkdir -p "$RCLONE_CONFIG_DIR"
    chmod 755 "$RCLONE_CONFIG_DIR"
    {
        echo "[gdrive]"
        echo "type = drive"
        echo "scope = drive"
        echo "service_account_file = $INSTANCES_DIR/$instance/gcp-credentials.json"
        echo "team_drive = $team_drive_id"
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

# Fable: "ufw status" is never trusted below as proof the firewall works.
# It derives "Status: active" from the existence of the ufw-* chains, not
# from the INPUT jumps that make them reachable — so it stayed green
# through the 2026-08-29 UAT lockout (INPUT flushed under an active ufw).
# While the chains exist, every ufw command (default/allow/enable/reload/
# force-reload) skips rule installation, so the broken state is
# unrepairable from inside ufw. The INPUT jump is the only reliable
# signal that the ruleset is actually wired in.
ufw_reports_active() {
    ufw status 2>/dev/null | grep -q '^Status: active'
}

ufw_recovery_hint() {
    echo "  The kernel is not running ufw's ruleset; the next ufw policy change" >&2
    echo "  would silently drop all traffic (no established-connections rule," >&2
    echo "  no allows, no logging) — the 2026-08-29 UAT lockout." >&2
    echo "  Recover with a REBOOT: boot-time ufw-init performs a genuine install." >&2
    echo "  The in-place alternative (iptables -F && iptables -X, both families," >&2
    echo "  then 'ufw --force enable') resets the ENTIRE filter table — it" >&2
    echo "  destroys rules owned by others (Docker, Oracle InstanceServices), so" >&2
    echo "  it is only for hosts where ufw is the sole iptables user. ufw ships" >&2
    echo "  no scoped teardown: 'ufw-init flush-all' also clears foreign chains." >&2
}

assert_ufw_effective() {
    if ! iptables -C INPUT -j ufw-before-input 2>/dev/null; then
        echo "ERROR: ufw reports active but INPUT does not jump into ufw-before-input." >&2
        ufw_recovery_hint
        return 1
    fi
    # Fable: the incident flushed ip6tables too; a v4-wired/v6-orphaned host
    # would pass a v4-only check while IPv6 policy is unwired (and, after a
    # flush, wide open — policy ACCEPT), so both families are asserted.
    if grep -q '^IPV6=yes' /etc/default/ufw 2>/dev/null \
            && ! ip6tables -C INPUT -j ufw6-before-input 2>/dev/null; then
        echo "ERROR: ufw reports active but ip6tables INPUT does not jump into ufw6-before-input." >&2
        ufw_recovery_hint
        return 1
    fi
}
