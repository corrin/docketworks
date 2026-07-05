#!/bin/bash
set -euo pipefail

# Manage docketworks instances.
# Usage: instance.sh prepare-config <client> <env>
#        instance.sh create <client> <env> [--seed] [--fqdn <hostname>] [--no-start]
#        instance.sh reconfigure <client> <env> [--fqdn <hostname>] [--no-start]
#        instance.sh destroy <client> <env>
#        instance.sh list
#
# --no-start: create the instance but do NOT enable/restart celery-beat-* and
# celery-worker-* services, and drop a .dr-mode marker in the instance dir.
# This is the "cold standby" / DR mode: celery-beat+celery-worker would otherwise
# fire their first heartbeat (and hit Xero with live tokens) within ~5 min of
# creation, which is the wrong posture for a standby that shares creds with a
# live primary. The marker also makes future deploy.sh runs leave the services
# alone — to "go live", `rm .dr-mode` then enable+start the units by hand.
#
# Naming convention:
#   Instance name: <client>-<env>     (e.g., msm-uat)     — directory, systemd unit suffix
#   Database:      dw_<client>_<env>  (e.g., dw_msm_uat)
#   OS user:       dw_<client>_<env>  (e.g., dw_msm_uat)  — same string as the DB role
#   URL:           <client>-<env>.docketworks.site

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TEMPLATE_DIR="$SCRIPT_DIR/templates"
source "$SCRIPT_DIR/common.sh"
source "$SCRIPT_DIR/release-utils.sh"

# Escape special chars for sed replacement strings (handles / & \ in values)
sed_escape() { printf '%s\n' "$1" | sed 's/[&/|\\\"]/\\&/g'; }

json_string_or_null() {
    if [[ -z "$1" ]]; then
        printf 'null'
    else
        python3 -c 'import json, sys; print(json.dumps(sys.argv[1]))' "$1"
    fi
}

# Get the FQDN for an instance: custom if set, else <instance>.<domain>
get_fqdn() {
    local instance="$1"
    local fqdn_file="$INSTANCES_DIR/$instance/.fqdn"
    if [[ -f "$fqdn_file" ]]; then
        cat "$fqdn_file"
    else
        echo "${instance}.${DOMAIN}"
    fi
}

# Parse and validate <client> <env> args (shared by all commands except list)
parse_client_env() {
    if [[ $# -lt 2 ]]; then
        echo "Usage: $0 $COMMAND <client> <env>"
        echo "  env must be one of: $VALID_ENVS"
        exit 1
    fi

    CLIENT="$1"
    ENV="$2"

    if [[ ! "$CLIENT" =~ ^[a-z0-9]+$ ]]; then
        echo "ERROR: Client name must be lowercase alphanumeric (no hyphens)."
        exit 1
    fi
    validate_env "$ENV"

    INSTANCE="${CLIENT}-${ENV}"
}

# ============================================================
# prepare-config
# ============================================================
do_prepare_config() {
    parse_client_env "$@"

    local CREDS_FILE="$CONFIG_DIR/$INSTANCE.credentials.env"
    if [[ -f "$CREDS_FILE" ]]; then
        echo "Credentials file already exists at:"
        echo "  $CREDS_FILE"
        echo ""
        echo "Edit it directly, or delete it and re-run to start fresh."
        exit 0
    fi

    ensure_config_dir
    sed "s|__INSTANCE__|$INSTANCE|g" "$TEMPLATE_DIR/credentials-instance.template" \
        > "$CREDS_FILE"
    chown root:root "$CREDS_FILE"
    chmod 600 "$CREDS_FILE"

    echo ""
    echo "============================================================"
    echo "  Credentials file created at:"
    echo "    $CREDS_FILE"
    echo ""
    echo "  Fill it out, then run:"
    echo "    sudo $0 create $CLIENT $ENV"
    echo ""
    echo "  See instructions in the file for Xero app setup."
    echo "============================================================"
}

generate_secret() {
    python3 -c 'import secrets; print(secrets.token_urlsafe(50))'
}

generate_password() {
    openssl rand -base64 24 | tr -d '/+=' | head -c 32
}

require_instance_credentials() {
    local creds_file="$1"

    if [[ ! -f "$creds_file" ]]; then
        echo "ERROR: No credentials file found at $creds_file"
        echo ""
        echo "Run prepare-config first:"
        echo "  sudo $0 prepare-config $CLIENT $ENV"
        exit 1
    fi

    require_root_owned_credentials_file "$creds_file"

    # Safe only after the root-owned/mode guard above: source executes shell.
    set -a
    # shellcheck source=/dev/null  # runtime credentials file, path not statically known
    source "$creds_file"
    set +a

    local MISSING=()
    [[ -z "${XERO_DEFAULT_USER_ID:-}" ]] && MISSING+=("XERO_DEFAULT_USER_ID")
    [[ -z "${GCP_CREDENTIALS:-}" ]] && MISSING+=("GCP_CREDENTIALS")
    [[ -z "${EMAIL_HOST_USER:-}" ]] && MISSING+=("EMAIL_HOST_USER")
    [[ -z "${EMAIL_HOST_PASSWORD:-}" ]] && MISSING+=("EMAIL_HOST_PASSWORD")
    [[ -z "${DJANGO_ADMINS:-}" ]] && MISSING+=("DJANGO_ADMINS")
    [[ -z "${EMAIL_BCC:-}" ]] && MISSING+=("EMAIL_BCC")
    [[ -z "${ANTHROPIC_API_KEY:-}" ]] && MISSING+=("ANTHROPIC_API_KEY")
    [[ -z "${GEMINI_API_KEY:-}" ]] && MISSING+=("GEMINI_API_KEY")
    [[ -z "${MISTRAL_API_KEY:-}" ]] && MISSING+=("MISTRAL_API_KEY")
    [[ -z "${E2E_TEST_USERNAME:-}" ]] && MISSING+=("E2E_TEST_USERNAME")
    [[ -z "${E2E_TEST_PASSWORD:-}" ]] && MISSING+=("E2E_TEST_PASSWORD")
    [[ -z "${XERO_USERNAME:-}" ]] && MISSING+=("XERO_USERNAME")
    [[ -z "${XERO_PASSWORD:-}" ]] && MISSING+=("XERO_PASSWORD")
    [[ -z "${XERO_CLIENT_ID:-}" ]] && MISSING+=("XERO_CLIENT_ID")
    [[ -z "${XERO_CLIENT_SECRET:-}" ]] && MISSING+=("XERO_CLIENT_SECRET")
    [[ -z "${XERO_WEBHOOK_KEY:-}" ]] && MISSING+=("XERO_WEBHOOK_KEY")
    [[ -z "${XERO_REDIRECT_URI:-}" ]] && MISSING+=("XERO_REDIRECT_URI")

    PHONE_PROVIDER_DOWNLOADS_ENABLED="${PHONE_PROVIDER_DOWNLOADS_ENABLED:-false}"
    PHONE_PROVIDER_RECORDING_DELETION_ENABLED="${PHONE_PROVIDER_RECORDING_DELETION_ENABLED:-false}"
    if [[ "$PHONE_PROVIDER_DOWNLOADS_ENABLED" == "true" || "$PHONE_PROVIDER_RECORDING_DELETION_ENABLED" == "true" ]]; then
        [[ -z "${PHONE_PROVIDER_BASE_URL:-}" ]] && MISSING+=("PHONE_PROVIDER_BASE_URL")
        [[ -z "${PHONE_PROVIDER_USERNAME:-}" ]] && MISSING+=("PHONE_PROVIDER_USERNAME")
        [[ -z "${PHONE_PROVIDER_PASSWORD:-}" ]] && MISSING+=("PHONE_PROVIDER_PASSWORD")
        [[ -z "${PHONE_PROVIDER_ACCOUNT_CODE:-}" ]] && MISSING+=("PHONE_PROVIDER_ACCOUNT_CODE")
    fi

    if [[ ${#MISSING[@]} -gt 0 ]]; then
        echo "ERROR: Missing required values in $creds_file:"
        for var in "${MISSING[@]}"; do
            echo "  - $var"
        done
        exit 1
    fi

    if [[ ! -f "$GCP_CREDENTIALS" ]]; then
        echo "ERROR: GCP_CREDENTIALS file not found: $GCP_CREDENTIALS"
        echo "  Provide a valid path to a GCP service account JSON key in $creds_file"
        exit 1
    fi
}

render_instance_env() {
    local instance_dir="$1"
    local instance_user="$2"
    local db_name="$3"
    local db_user="$4"
    local scrub_db_name="$5"
    local test_db_user="$6"
    local fqdn="$7"

    local env_file="$instance_dir/.env"
    local db_password test_db_password secret_key bearer_secret
    db_password="$(read_env_value "$env_file" DB_PASSWORD)"
    test_db_password="$(read_env_value "$env_file" TEST_DB_PASSWORD)"
    secret_key="$(read_env_value "$env_file" SECRET_KEY)"
    bearer_secret="$(read_env_value "$env_file" BEARER_SECRET)"

    [[ -n "$db_password" ]] || db_password="$(generate_password)"
    [[ -n "$test_db_password" ]] || test_db_password="$(generate_password)"
    [[ -n "$secret_key" ]] || secret_key="$(generate_secret)"
    [[ -n "$bearer_secret" ]] || bearer_secret="$(generate_secret)"

    local ESC_XERO_DEFAULT_USER_ID
    ESC_XERO_DEFAULT_USER_ID="$(sed_escape "$XERO_DEFAULT_USER_ID")"
    local ESC_EMAIL_HOST_USER ESC_EMAIL_HOST_PASSWORD ESC_DJANGO_ADMINS ESC_EMAIL_BCC
    ESC_EMAIL_HOST_USER="$(sed_escape "$EMAIL_HOST_USER")"
    ESC_EMAIL_HOST_PASSWORD="$(sed_escape "$EMAIL_HOST_PASSWORD")"
    ESC_DJANGO_ADMINS="$(sed_escape "$DJANGO_ADMINS")"
    ESC_EMAIL_BCC="$(sed_escape "$EMAIL_BCC")"
    local gcp_dest="$instance_dir/gcp-credentials.json"
    local tmp_env
    tmp_env="$(mktemp "$instance_dir/.env.tmp.XXXXXX")"

    sed \
        -e "s|__INSTANCE__|$INSTANCE|g" \
        -e "s|__DOMAIN__|$DOMAIN|g" \
        -e "s|__FQDN__|$fqdn|g" \
        -e "s|__DB_NAME__|$db_name|g" \
        -e "s|__DB_USER__|$db_user|g" \
        -e "s|__DB_PASSWORD__|$db_password|g" \
        -e "s|__SCRUB_DB_NAME__|$scrub_db_name|g" \
        -e "s|__TEST_DB_USER__|$test_db_user|g" \
        -e "s|__TEST_DB_PASSWORD__|$test_db_password|g" \
        -e "s|__SECRET_KEY__|$secret_key|g" \
        -e "s|__BEARER_SECRET__|$bearer_secret|g" \
        -e "s|__XERO_DEFAULT_USER_ID__|$ESC_XERO_DEFAULT_USER_ID|g" \
        -e "s|__GCP_CREDENTIALS_PATH__|$gcp_dest|g" \
        -e "s|__EMAIL_HOST_USER__|$ESC_EMAIL_HOST_USER|g" \
        -e "s|__EMAIL_HOST_PASSWORD__|$ESC_EMAIL_HOST_PASSWORD|g" \
        -e "s|__DJANGO_ADMINS__|$ESC_DJANGO_ADMINS|g" \
        -e "s|__EMAIL_BCC__|$ESC_EMAIL_BCC|g" \
        "$TEMPLATE_DIR/env-instance.template" > "$tmp_env"

    local shared_env="$BASE_DIR/shared.env"
    if [[ ! -f "$shared_env" ]]; then
        rm -f "$tmp_env"
        echo "ERROR: $shared_env not found. Run server-setup.sh first."
        exit 1
    fi
    echo "" >> "$tmp_env"
    grep '^GOOGLE_MAPS_API_KEY=' "$shared_env" >> "$tmp_env"
    chown "$instance_user:$instance_user" "$tmp_env"
    chmod 600 "$tmp_env"
    mv "$tmp_env" "$env_file"
}

render_ai_providers_fixture() {
    local instance_dir="$1"
    local instance_user="$2"
    local fixture_dir="$instance_dir/.fixtures"

    log "Generating AI providers fixture..."
    mkdir -p "$fixture_dir"
    local ESC_ANTHROPIC_API_KEY ESC_GEMINI_API_KEY ESC_MISTRAL_API_KEY
    ESC_ANTHROPIC_API_KEY="$(sed_escape "$ANTHROPIC_API_KEY")"
    ESC_GEMINI_API_KEY="$(sed_escape "$GEMINI_API_KEY")"
    ESC_MISTRAL_API_KEY="$(sed_escape "$MISTRAL_API_KEY")"
    sed \
        -e "s|__ANTHROPIC_API_KEY__|$ESC_ANTHROPIC_API_KEY|g" \
        -e "s|__GEMINI_API_KEY__|$ESC_GEMINI_API_KEY|g" \
        -e "s|__MISTRAL_API_KEY__|$ESC_MISTRAL_API_KEY|g" \
        "$TEMPLATE_DIR/ai-providers.json.template" \
        > "$fixture_dir/ai_providers.json"
    chown -R "$instance_user:$instance_user" "$fixture_dir"
    chmod 700 "$fixture_dir"
    chmod 600 "$fixture_dir/ai_providers.json"
}

render_xero_apps_fixture() {
    local instance_dir="$1"
    local instance_user="$2"
    local fixture_dir="$instance_dir/.fixtures"

    log "Generating Xero apps fixture..."
    mkdir -p "$fixture_dir"
    local ESC_XERO_CLIENT_ID ESC_XERO_CLIENT_SECRET ESC_XERO_WEBHOOK_KEY ESC_XERO_REDIRECT_URI
    ESC_XERO_CLIENT_ID="$(sed_escape "$XERO_CLIENT_ID")"
    ESC_XERO_CLIENT_SECRET="$(sed_escape "$XERO_CLIENT_SECRET")"
    ESC_XERO_WEBHOOK_KEY="$(sed_escape "$XERO_WEBHOOK_KEY")"
    ESC_XERO_REDIRECT_URI="$(sed_escape "$XERO_REDIRECT_URI")"
    sed \
        -e "s|__INSTANCE__|$INSTANCE|g" \
        -e "s|__XERO_CLIENT_ID__|$ESC_XERO_CLIENT_ID|g" \
        -e "s|__XERO_CLIENT_SECRET__|$ESC_XERO_CLIENT_SECRET|g" \
        -e "s|__XERO_WEBHOOK_KEY__|$ESC_XERO_WEBHOOK_KEY|g" \
        -e "s|__XERO_REDIRECT_URI__|$ESC_XERO_REDIRECT_URI|g" \
        "$TEMPLATE_DIR/xero-apps.json.template" \
        > "$fixture_dir/xero_apps.json"
    chown -R "$instance_user:$instance_user" "$fixture_dir"
    chmod 700 "$fixture_dir"
    chmod 600 "$fixture_dir/xero_apps.json"
}

render_phone_provider_settings_fixture() {
    local instance_dir="$1"
    local instance_user="$2"
    local fixture_dir="$instance_dir/.fixtures"

    log "Generating phone provider settings fixture..."
    mkdir -p "$fixture_dir"
    local ESC_PHONE_PROVIDER_USERNAME ESC_PHONE_PROVIDER_PASSWORD ESC_PHONE_PROVIDER_ACCOUNT_CODE
    local PHONE_PROVIDER_BASE_URL_JSON
    ESC_PHONE_PROVIDER_USERNAME="$(sed_escape "${PHONE_PROVIDER_USERNAME:-}")"
    ESC_PHONE_PROVIDER_PASSWORD="$(sed_escape "${PHONE_PROVIDER_PASSWORD:-}")"
    ESC_PHONE_PROVIDER_ACCOUNT_CODE="$(sed_escape "${PHONE_PROVIDER_ACCOUNT_CODE:-}")"
    PHONE_PROVIDER_BASE_URL_JSON="$(sed_escape "$(json_string_or_null "${PHONE_PROVIDER_BASE_URL:-}")")"
    sed \
        -e "s|__PHONE_PROVIDER_DOWNLOADS_ENABLED__|${PHONE_PROVIDER_DOWNLOADS_ENABLED:-false}|g" \
        -e "s|__PHONE_PROVIDER_RECORDING_DELETION_ENABLED__|${PHONE_PROVIDER_RECORDING_DELETION_ENABLED:-false}|g" \
        -e "s|__PHONE_PROVIDER_BASE_URL_JSON__|$PHONE_PROVIDER_BASE_URL_JSON|g" \
        -e "s|__PHONE_PROVIDER_USERNAME__|$ESC_PHONE_PROVIDER_USERNAME|g" \
        -e "s|__PHONE_PROVIDER_PASSWORD__|$ESC_PHONE_PROVIDER_PASSWORD|g" \
        -e "s|__PHONE_PROVIDER_ACCOUNT_CODE__|$ESC_PHONE_PROVIDER_ACCOUNT_CODE|g" \
        "$TEMPLATE_DIR/phone-provider-settings.json.template" \
        > "$fixture_dir/phone_provider_settings.json"
    chown -R "$instance_user:$instance_user" "$fixture_dir"
    chmod 700 "$fixture_dir"
    chmod 600 "$fixture_dir/phone_provider_settings.json"
}

# ============================================================
# create / reconfigure
# ============================================================
do_configure() {
    local allow_seed="$1"
    local command_name="$2"
    shift 2

    parse_client_env "$@"
    shift 2

    local SEED=false
    local CUSTOM_FQDN=""
    local NO_START=false
    local parsed
    local long_opts="fqdn:,no-start"
    if [[ "$allow_seed" == "true" ]]; then
        long_opts="seed,$long_opts"
    fi
    if ! parsed=$(getopt -o '' --long "$long_opts" -n "$(basename "$0") $command_name" -- "$@"); then
        if [[ "$allow_seed" == "true" ]]; then
            echo "Usage: $(basename "$0") $command_name <client> <env> [--seed] [--fqdn <hostname>] [--no-start]" >&2
        else
            echo "Usage: $(basename "$0") $command_name <client> <env> [--fqdn <hostname>] [--no-start]" >&2
        fi
        exit 1
    fi
    eval set -- "$parsed"
    while true; do
        case "$1" in
            --seed)     SEED=true;        shift ;;
            --fqdn)     CUSTOM_FQDN="$2"; shift 2 ;;
            --no-start) NO_START=true;    shift ;;
            --)         shift; break ;;
        esac
    done
    if [[ $# -gt 0 ]]; then
        echo "ERROR: Unexpected arguments to '$command_name': $*" >&2
        exit 1
    fi

    local CREDS_FILE="$CONFIG_DIR/$INSTANCE.credentials.env"
    require_instance_credentials "$CREDS_FILE"

    local INSTANCE_DIR="$INSTANCES_DIR/$INSTANCE"
    local INSTANCE_USER
    INSTANCE_USER="$(instance_user "$INSTANCE")"
    local DB_NAME="dw_${CLIENT}_${ENV}"
    local DB_USER="dw_${CLIENT}_${ENV}"
    local SCRUB_DB_NAME="dw_${CLIENT}_${ENV}_scrub"
    local TEST_DB_USER="dw_${CLIENT}_${ENV}_test"
    local TEST_DB_NAME="$TEST_DB_USER"
    local IS_EXISTING=false
    local NEEDS_APP_BOOTSTRAP=false
    if [[ -L "$INSTANCE_DIR/app" || -L "$INSTANCE_DIR/current" || -f "$INSTANCE_DIR/.env" ]]; then
        IS_EXISTING=true
    fi
    if [[ ! -f "$INSTANCE_DIR/.env" ]]; then
        NEEDS_APP_BOOTSTRAP=true
    fi
    if [[ -f "$INSTANCE_DIR/.env" && ! -L "$INSTANCE_DIR/app" && ! -L "$INSTANCE_DIR/current" ]]; then
        echo "ERROR: $INSTANCE_DIR has config but no app/current release link." >&2
        echo "  Restore or recreate the instance instead of reconfiguring partial state." >&2
        exit 1
    fi
    if [[ "$IS_EXISTING" == "true" && "$SEED" == "true" ]]; then
        echo "ERROR: --seed is only valid when creating a new instance." >&2
        echo "  Existing instance: $INSTANCE_DIR" >&2
        exit 1
    fi

    log "=========================================="
    if [[ "$IS_EXISTING" == "true" ]]; then
        log "Reconfiguring docketworks instance: $INSTANCE"
    else
        log "Creating docketworks instance: $INSTANCE"
    fi
    log "  Client:    $CLIENT"
    log "  Env:       $ENV"
    log "  Directory: $INSTANCE_DIR"
    log "  User:      $INSTANCE_USER"
    log "  Database:  $DB_NAME"
    log "  URL:       https://$INSTANCE.$DOMAIN"
    log "=========================================="

    # --- Create per-instance OS user ---
    if id "$INSTANCE_USER" &>/dev/null; then
        log "User '$INSTANCE_USER' already exists, skipping."
    else
        log "Creating system user '$INSTANCE_USER'..."
        useradd --system --shell /bin/bash --no-create-home --home-dir "$INSTANCE_DIR" "$INSTANCE_USER"
        log "  Created user '$INSTANCE_USER' (no supplementary groups)."
    fi

    # --- Set disk quota for instance user ---
    # quotaon -p exits 0 whether quotas are on or off; parse its output instead.
    # Format: "user quota on <mount> (<device>) is on|off"
    if command -v setquota &>/dev/null; then
        local QUOTA_MOUNT QUOTA_STATUS
        QUOTA_MOUNT="$(df --output=target "$INSTANCES_DIR" | tail -1)"
        QUOTA_STATUS="$(quotaon -pu "$QUOTA_MOUNT" 2>/dev/null || true)"
        if [[ "$QUOTA_STATUS" == *"is on"* ]]; then
            log "Setting disk quota for $INSTANCE_USER: soft=$QUOTA_SOFT hard=$QUOTA_HARD"
            setquota -u "$INSTANCE_USER" "$QUOTA_SOFT" "$QUOTA_HARD" 0 0 "$QUOTA_MOUNT"
        else
            log "WARNING: Filesystem quotas not enabled on $QUOTA_MOUNT"
            log "  Enable with: sudo quotacheck -cum $QUOTA_MOUNT && sudo quotaon $QUOTA_MOUNT"
        fi
    else
        log "WARNING: setquota not found — install quota package: sudo apt install quota"
    fi

    local FQDN CERT_DOMAIN
    if [[ -n "$CUSTOM_FQDN" ]]; then
        FQDN="$CUSTOM_FQDN"
        CERT_DOMAIN="$CUSTOM_FQDN"
    elif [[ "$IS_EXISTING" == "true" && -f "$INSTANCE_DIR/.fqdn" ]]; then
        FQDN="$(cat "$INSTANCE_DIR/.fqdn")"
        if [[ "$FQDN" == *".$DOMAIN" ]]; then
            CERT_DOMAIN="$DOMAIN"
        else
            CERT_DOMAIN="$FQDN"
        fi
    else
        FQDN="${INSTANCE}.${DOMAIN}"
        CERT_DOMAIN="$DOMAIN"
    fi

    log "Ensuring instance directory structure..."
    mkdir -p "$INSTANCE_DIR"/{logs,mediafiles,dropbox,phone-recordings,session-replays}
    ensure_instance_backup_dir "$INSTANCE" "$INSTANCE_USER"
    chown "$INSTANCE_USER:www-data" "$INSTANCE_DIR"
    chmod 750 "$INSTANCE_DIR"
    chown "$INSTANCE_USER:$INSTANCE_USER" "$INSTANCE_DIR/logs" "$INSTANCE_DIR/dropbox"
    chmod 700 "$INSTANCE_DIR/logs"
    chmod 700 "$INSTANCE_DIR/dropbox"
    chown "$INSTANCE_USER:www-data" "$INSTANCE_DIR/mediafiles"
    chmod 750 "$INSTANCE_DIR/mediafiles"
    chown "$INSTANCE_USER:$INSTANCE_USER" \
        "$INSTANCE_DIR/phone-recordings" \
        "$INSTANCE_DIR/session-replays"
    chmod 700 "$INSTANCE_DIR/phone-recordings" "$INSTANCE_DIR/session-replays"
    require_root_owned_credentials_file "$CREDS_FILE"
    cp "$GCP_CREDENTIALS" "$INSTANCE_DIR/gcp-credentials.json"
    chown "$INSTANCE_USER:$INSTANCE_USER" "$INSTANCE_DIR/gcp-credentials.json"
    chmod 600 "$INSTANCE_DIR/gcp-credentials.json"

    log "Writing rclone config for $INSTANCE to $(instance_rclone_config "$INSTANCE")..."
    write_instance_rclone_config \
        "$INSTANCE" \
        "$INSTANCE_USER" \
        "${BACKUP_GDRIVE_ROOT_FOLDER_ID:-}"
    echo "$FQDN" > "$INSTANCE_DIR/.fqdn"
    chown "$INSTANCE_USER:$INSTANCE_USER" "$INSTANCE_DIR/.fqdn"

    cat > "$INSTANCE_DIR/.bash_profile" <<'BASH_PROFILE'
source ~/app/.venv/bin/activate
set -a; source ~/.env; set +a
cd ~/app
BASH_PROFILE
    chown "$INSTANCE_USER:$INSTANCE_USER" "$INSTANCE_DIR/.bash_profile"
    chmod 644 "$INSTANCE_DIR/.bash_profile"

    log "Rendering .env from template (preserving generated secrets)..."
    render_instance_env \
        "$INSTANCE_DIR" \
        "$INSTANCE_USER" \
        "$DB_NAME" \
        "$DB_USER" \
        "$SCRUB_DB_NAME" \
        "$TEST_DB_USER" \
        "$FQDN"

    local DB_PASSWORD TEST_DB_PASSWORD
    DB_PASSWORD="$(read_env_value "$INSTANCE_DIR/.env" DB_PASSWORD)"
    TEST_DB_PASSWORD="$(read_env_value "$INSTANCE_DIR/.env" TEST_DB_PASSWORD)"
    if [[ -z "$TEST_DB_PASSWORD" ]]; then
        echo "ERROR: TEST_DB_PASSWORD missing from $INSTANCE_DIR/.env" >&2
        echo "  This instance was created before per-tenant test roles were added." >&2
        echo "  Run the one-off migration first:" >&2
        echo "    sudo scripts/server/migrate-test-role.sh $INSTANCE" >&2
        exit 1
    fi
    # Escape single quotes for safe SQL interpolation
    local SQL_PASSWORD="${DB_PASSWORD//\'/\'\'}"
    local SQL_TEST_PASSWORD="${TEST_DB_PASSWORD//\'/\'\'}"
    log "Ensuring databases $DB_NAME, $SCRUB_DB_NAME, $TEST_DB_NAME and roles $DB_USER, $TEST_DB_USER exist..."
    sudo -u postgres psql <<EOSQL
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '$DB_USER') THEN
        CREATE ROLE "$DB_USER" WITH LOGIN PASSWORD '$SQL_PASSWORD';
    ELSE
        ALTER ROLE "$DB_USER" WITH PASSWORD '$SQL_PASSWORD';
    END IF;
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '$TEST_DB_USER') THEN
        CREATE ROLE "$TEST_DB_USER" WITH LOGIN PASSWORD '$SQL_TEST_PASSWORD';
    ELSE
        ALTER ROLE "$TEST_DB_USER" WITH PASSWORD '$SQL_TEST_PASSWORD';
    END IF;
END
\$\$;
SELECT 'CREATE DATABASE "$DB_NAME" OWNER "$DB_USER"'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '$DB_NAME')\gexec
GRANT ALL PRIVILEGES ON DATABASE "$DB_NAME" TO "$DB_USER";
SELECT 'CREATE DATABASE "$SCRUB_DB_NAME" OWNER "$DB_USER"'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '$SCRUB_DB_NAME')\gexec
GRANT ALL PRIVILEGES ON DATABASE "$SCRUB_DB_NAME" TO "$DB_USER";
SELECT 'CREATE DATABASE "$TEST_DB_NAME" OWNER "$TEST_DB_USER"'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '$TEST_DB_NAME')\gexec
GRANT ALL PRIVILEGES ON DATABASE "$TEST_DB_NAME" TO "$TEST_DB_USER";
EOSQL

    ensure_instance_app_link "$INSTANCE"
    if [[ ! -L "$INSTANCE_DIR/app" ]]; then
        local TARGET_SHA
        fetch_local_repo
        TARGET_SHA="$(resolve_release_ref origin/main)"
        log "Creating app release link from origin/main SHA $TARGET_SHA"
        ensure_release "$TARGET_SHA"
        switch_instance_release "$INSTANCE" "$TARGET_SHA"
        chown -h "$INSTANCE_USER:$INSTANCE_USER" "$INSTANCE_DIR/app"
    fi

    if [[ "$NEEDS_APP_BOOTSTRAP" == "true" ]]; then
        log "Running Django migrate..."
        "$SCRIPT_DIR/dw-run.sh" "$INSTANCE" python manage.py migrate --no-input
    fi

    render_ai_providers_fixture "$INSTANCE_DIR" "$INSTANCE_USER"
    log "Loading AI providers..."
    local AI_PROVIDERS_FIXTURE="$INSTANCE_DIR/.fixtures/ai_providers.json"
    "$SCRIPT_DIR/dw-run.sh" "$INSTANCE" python manage.py shell -c \
        "from django.core.management import call_command; from apps.workflow.models import AIProvider; print('AIProvider already configured; skipping ai_providers.json load') if AIProvider.objects.exists() else call_command('loaddata', '$AI_PROVIDERS_FIXTURE')"
    rm -f "$AI_PROVIDERS_FIXTURE"

    render_xero_apps_fixture "$INSTANCE_DIR" "$INSTANCE_USER"
    log "Loading Xero apps..."
    local XERO_APPS_FIXTURE="$INSTANCE_DIR/.fixtures/xero_apps.json"
    "$SCRIPT_DIR/dw-run.sh" "$INSTANCE" python manage.py shell -c \
        "from django.core.management import call_command; from apps.workflow.models import XeroApp; print('XeroApp already configured; skipping xero_apps.json load') if XeroApp.objects.exists() else call_command('loaddata', '$XERO_APPS_FIXTURE')"
    rm -f "$XERO_APPS_FIXTURE"

    render_phone_provider_settings_fixture "$INSTANCE_DIR" "$INSTANCE_USER"
    log "Loading phone provider settings..."
    local PHONE_PROVIDER_SETTINGS_FIXTURE="$INSTANCE_DIR/.fixtures/phone_provider_settings.json"
    "$SCRIPT_DIR/dw-run.sh" "$INSTANCE" python manage.py shell -c \
        "from django.core.management import call_command; from apps.crm.models import PhoneProviderSettings; settings = PhoneProviderSettings.get_solo(); configured = bool(settings.base_url or settings.username or settings.account_code); print('PhoneProviderSettings already configured; skipping phone_provider_settings.json load') if configured else call_command('loaddata', '$PHONE_PROVIDER_SETTINGS_FIXTURE')"
    rm -f "$PHONE_PROVIDER_SETTINGS_FIXTURE"

    if [[ "$NEEDS_APP_BOOTSTRAP" == "true" ]]; then
        log "Creating initial admin user..."
        # --admin-only: ensure the default admin exists but do NOT reset staff
        # passwords. The password reset is strictly part of restore-prod-to-nonprod
        # (see docs/restore-prod-to-nonprod.md), never instance creation.
        "$SCRIPT_DIR/dw-run.sh" "$INSTANCE" python scripts/setup_dev_logins.py --admin-only

        if [[ "$SEED" == "true" ]]; then
            log "Loading demo fixtures..."
            "$SCRIPT_DIR/dw-run.sh" "$INSTANCE" python manage.py loaddata demo_fixtures
        fi
    fi

    if [[ "$NO_START" == "true" ]]; then
        log "DR mode: writing $INSTANCE_DIR/.dr-mode (celery-beat+celery-worker will not be auto-started)"
        touch "$INSTANCE_DIR/.dr-mode"
        chown "$INSTANCE_USER:$INSTANCE_USER" "$INSTANCE_DIR/.dr-mode"
        chmod 644 "$INSTANCE_DIR/.dr-mode"
    fi

    log "Installing systemd service gunicorn-$INSTANCE..."
    sed \
        -e "s|__INSTANCE__|$INSTANCE|g" \
        -e "s|__INSTANCE_USER__|$INSTANCE_USER|g" \
        "$TEMPLATE_DIR/gunicorn-instance.service.template" \
        > "/etc/systemd/system/gunicorn-$INSTANCE.service"
    systemctl daemon-reload
    if [[ -f "$INSTANCE_DIR/.dr-mode" ]]; then
        # Cold-standby: docs/server_setup.md and deploy.sh both gate
        # gunicorn on .dr-mode so the box doesn't accept HTTP traffic
        # before DNS cutover. The unit file is rendered above so "go
        # live" is just `rm .dr-mode && systemctl enable --now ...`.
        log "  DR mode: skipping enable/restart of gunicorn-$INSTANCE"
    else
        systemctl enable "gunicorn-$INSTANCE"
        systemctl restart "gunicorn-$INSTANCE"
    fi

    log "Installing systemd service celery-beat-$INSTANCE..."
    sed \
        -e "s|__INSTANCE__|$INSTANCE|g" \
        -e "s|__INSTANCE_USER__|$INSTANCE_USER|g" \
        "$TEMPLATE_DIR/celery-beat-instance.service.template" \
        > "/etc/systemd/system/celery-beat-$INSTANCE.service"
    systemctl daemon-reload
    if [[ -f "$INSTANCE_DIR/.dr-mode" ]]; then
        log "  DR mode: skipping enable/restart of celery-beat-$INSTANCE"
    else
        systemctl enable "celery-beat-$INSTANCE"
        systemctl restart "celery-beat-$INSTANCE"
    fi

    log "Installing systemd service celery-worker-$INSTANCE..."
    sed \
        -e "s|__INSTANCE__|$INSTANCE|g" \
        -e "s|__INSTANCE_USER__|$INSTANCE_USER|g" \
        "$TEMPLATE_DIR/celery-worker-instance.service.template" \
        > "/etc/systemd/system/celery-worker-$INSTANCE.service"
    systemctl daemon-reload
    if [[ -f "$INSTANCE_DIR/.dr-mode" ]]; then
        log "  DR mode: skipping enable/restart of celery-worker-$INSTANCE"
    else
        systemctl enable "celery-worker-$INSTANCE"
        systemctl restart "celery-worker-$INSTANCE"
    fi

    log "Installing backup timer backup-db-$INSTANCE..."
    render_backup_units "$INSTANCE" "$INSTANCE_USER" "$TEMPLATE_DIR"
    systemctl daemon-reload
    systemctl enable --now "backup-db-$INSTANCE.timer"
    log "  Enabled nightly backup timer backup-db-$INSTANCE.timer"

    log "Installing sudoers drop-in for $INSTANCE_USER..."
    local SUDOERS_TMP
    SUDOERS_TMP="$(mktemp)"
    sed \
        -e "s|__INSTANCE__|$INSTANCE|g" \
        -e "s|__INSTANCE_USER__|$INSTANCE_USER|g" \
        "$TEMPLATE_DIR/sudoers-instance.template" \
        > "$SUDOERS_TMP"
    visudo -cf "$SUDOERS_TMP"
    install -m 0440 -o root -g root "$SUDOERS_TMP" "/etc/sudoers.d/$INSTANCE_USER"
    rm -f "$SUDOERS_TMP"

    log "Installing Nginx config for $FQDN..."
    sed \
        -e "s|__INSTANCE__|$INSTANCE|g" \
        -e "s|__FQDN__|$FQDN|g" \
        -e "s|__CERT_DOMAIN__|$CERT_DOMAIN|g" \
        "$TEMPLATE_DIR/nginx-instance.conf.template" \
        > "/etc/nginx/sites-available/docketworks-$INSTANCE"
    ln -sf "/etc/nginx/sites-available/docketworks-$INSTANCE" "/etc/nginx/sites-enabled/"

    local CERT_PATH="/etc/letsencrypt/live/$CERT_DOMAIN/fullchain.pem"
    if [[ -f "$CERT_PATH" ]]; then
        nginx -t && systemctl reload nginx
    else
        log "  NOTE: SSL cert not yet at $CERT_PATH — skipping nginx reload."
        log "  After DNS cutover: sudo certbot --nginx -d $FQDN"
    fi

    log "=========================================="
    if [[ "$IS_EXISTING" == "true" ]]; then
        log "Instance '$INSTANCE' reconfigured successfully"
    else
        log "Instance '$INSTANCE' created successfully"
    fi
    log "  URL:        https://$FQDN"
    log "  Directory:  $INSTANCE_DIR"
    log "  User:       $INSTANCE_USER"
    log "  Database:   $DB_NAME"
    log "  Service:    gunicorn-$INSTANCE"
    log "  Beat:       celery-beat-$INSTANCE"
    log "=========================================="

    echo ""
    echo "  Instance is live at: https://$FQDN"
}

do_create() {
    do_configure true create "$@"
}

do_reconfigure() {
    do_configure false reconfigure "$@"
}

# ============================================================
# destroy
# ============================================================
do_destroy() {
    parse_client_env "$@"

    local INSTANCE_DIR="$INSTANCES_DIR/$INSTANCE"
    local INSTANCE_USER
    INSTANCE_USER="$(instance_user "$INSTANCE")"
    local DB_NAME="dw_${CLIENT}_${ENV}"
    local DB_USER="dw_${CLIENT}_${ENV}"
    local SCRUB_DB_NAME="dw_${CLIENT}_${ENV}_scrub"
    local TEST_DB_USER="dw_${CLIENT}_${ENV}_test"
    local TEST_DB_NAME="$TEST_DB_USER"

    echo "=== Destroying instance: $INSTANCE ==="
    echo ""
    echo "  This will permanently delete:"
    echo "    - Directory: $INSTANCE_DIR"
    echo "    - Database:  $DB_NAME"
    echo "    - Database:  $SCRUB_DB_NAME"
    echo "    - Database:  $TEST_DB_NAME"
    echo "    - DB role:   $DB_USER"
    echo "    - DB role:   $TEST_DB_USER"
    echo "    - User:      $INSTANCE_USER"
    echo "    - Service:   gunicorn-$INSTANCE"
    echo "    - Service:   celery-beat-$INSTANCE"
    echo "    - Timer:     backup-db-$INSTANCE"
    echo "    - Nginx:     docketworks-$INSTANCE"
    echo ""
    read -r -p "Are you sure? (yes/no): " CONFIRM
    if [[ "$CONFIRM" != "yes" ]]; then
        echo "Aborted."
        exit 0
    fi

    # --- Stop and remove systemd services ---
    if systemctl is-active --quiet "gunicorn-$INSTANCE" 2>/dev/null; then
        echo "=== Stopping Gunicorn service ==="
        systemctl stop "gunicorn-$INSTANCE"
    fi
    if [[ -f "/etc/systemd/system/gunicorn-$INSTANCE.service" ]]; then
        echo "=== Removing Gunicorn service ==="
        systemctl disable "gunicorn-$INSTANCE" 2>/dev/null || true
        rm -f "/etc/systemd/system/gunicorn-$INSTANCE.service"
        systemctl daemon-reload
    fi

    if systemctl is-active --quiet "celery-beat-$INSTANCE" 2>/dev/null; then
        echo "=== Stopping Celery Beat service ==="
        systemctl stop "celery-beat-$INSTANCE"
    fi
    if [[ -f "/etc/systemd/system/celery-beat-$INSTANCE.service" ]]; then
        echo "=== Removing Celery Beat service ==="
        systemctl disable "celery-beat-$INSTANCE" 2>/dev/null || true
        rm -f "/etc/systemd/system/celery-beat-$INSTANCE.service"
        systemctl daemon-reload
    fi
    # Legacy: clean up the pre-celery-beat scheduler-$INSTANCE unit if present
    # (from an instance created before the apscheduler→celery-beat migration).
    if systemctl is-active --quiet "scheduler-$INSTANCE" 2>/dev/null; then
        systemctl stop "scheduler-$INSTANCE"
    fi
    if [[ -f "/etc/systemd/system/scheduler-$INSTANCE.service" ]]; then
        systemctl disable "scheduler-$INSTANCE" 2>/dev/null || true
        rm -f "/etc/systemd/system/scheduler-$INSTANCE.service"
        systemctl daemon-reload
    fi
    if [[ -f "/etc/systemd/system/backup-db-$INSTANCE.timer" ]]; then
        echo "=== Removing Backup timer ==="
        systemctl disable "backup-db-$INSTANCE.timer" 2>/dev/null || true
        rm -f "/etc/systemd/system/backup-db-$INSTANCE.timer"
        systemctl daemon-reload
    fi
    if [[ -f "/etc/systemd/system/backup-db-$INSTANCE.service" ]]; then
        echo "=== Removing Backup service ==="
        rm -f "/etc/systemd/system/backup-db-$INSTANCE.service"
        systemctl daemon-reload
    fi

    # --- Remove sudoers drop-in ---
    if [[ -f "/etc/sudoers.d/$INSTANCE_USER" ]]; then
        echo "=== Removing sudoers drop-in ==="
        rm -f "/etc/sudoers.d/$INSTANCE_USER"
    fi

    # --- Remove Nginx config ---
    if [[ -f "/etc/nginx/sites-available/docketworks-$INSTANCE" ]]; then
        echo "=== Removing Nginx config ==="
        rm -f "/etc/nginx/sites-enabled/docketworks-$INSTANCE"
        rm -f "/etc/nginx/sites-available/docketworks-$INSTANCE"
        nginx -t && systemctl reload nginx
    fi

    # --- Drop databases and users ---
    echo "=== Dropping databases and users ==="
    sudo -u postgres psql -c "DROP DATABASE IF EXISTS \"$DB_NAME\";" || true
    sudo -u postgres psql -c "DROP DATABASE IF EXISTS \"$SCRUB_DB_NAME\";" || true
    sudo -u postgres psql -c "DROP DATABASE IF EXISTS \"$TEST_DB_NAME\";" || true
    sudo -u postgres psql -c "DROP ROLE IF EXISTS \"$DB_USER\";" || true
    sudo -u postgres psql -c "DROP ROLE IF EXISTS \"$TEST_DB_USER\";" || true

    # --- Remove files ---
    if [[ -d "$INSTANCE_DIR" ]]; then
        echo "=== Removing instance directory ==="
        rm -rf "$INSTANCE_DIR"
    fi

    # --- Remove OS user ---
    if id "$INSTANCE_USER" &>/dev/null; then
        echo "=== Removing user $INSTANCE_USER ==="
        userdel "$INSTANCE_USER"
    fi

    echo ""
    echo "=== Instance '$INSTANCE' destroyed ==="
}

# ============================================================
# list
# ============================================================
do_list() {
    if [[ ! -d "$INSTANCES_DIR" ]]; then
        echo "No instances found (directory $INSTANCES_DIR does not exist)."
        exit 0
    fi

    local INSTANCES=()
    for dir in "$INSTANCES_DIR"/*/; do
        [[ -d "$dir" ]] || continue
        INSTANCES+=("$(basename "$dir")")
    done

    if [[ ${#INSTANCES[@]} -eq 0 ]]; then
        echo "No instances found."
        exit 0
    fi

    printf "%-15s %-12s %-12s %-10s %-40s\n" "INSTANCE" "GUNICORN" "SCHEDULER" "SHA" "URL"
    printf "%-15s %-12s %-12s %-10s %-40s\n" "--------" "--------" "---------" "---" "---"

    for name in "${INSTANCES[@]}"; do
        local status sched_status sha
        if systemctl is-active --quiet "gunicorn-$name" 2>/dev/null; then
            status="running"
        elif systemctl is-enabled --quiet "gunicorn-$name" 2>/dev/null; then
            status="stopped"
        else
            status="no service"
        fi

        if systemctl is-active --quiet "celery-beat-$name" 2>/dev/null; then
            sched_status="running"
        elif systemctl is-enabled --quiet "celery-beat-$name" 2>/dev/null; then
            sched_status="stopped"
        else
            sched_status="no service"
        fi

        sha="$(instance_current_sha "$name")"
        if [[ -n "$sha" ]]; then
            sha="$(short_release_sha "$sha")"
        else
            sha="no release"
        fi

        printf "%-15s %-12s %-12s %-10s %-40s\n" "$name" "$status" "$sched_status" "$sha" "https://$(get_fqdn "$name")"
    done
}

# ============================================================
# main
# ============================================================
if [[ $# -lt 1 ]]; then
    echo "Usage: $0 {prepare-config|create|reconfigure|destroy|list} [args...]"
    echo "  prepare-config <client> <env>    — scaffold credentials file"
    echo "  create         <client> <env> [--seed] [--fqdn <hostname>] [--no-start]"
    echo "  reconfigure    <client> <env> [--fqdn <hostname>] [--no-start]"
    echo "  destroy        <client> <env>"
    echo "  list"
    exit 1
fi

COMMAND="$1"; shift

if [[ "$COMMAND" != "list" && $EUID -ne 0 ]]; then
    echo "ERROR: This script must be run as root (use sudo)."
    exit 1
fi

case "$COMMAND" in
    prepare-config) do_prepare_config "$@" ;;
    create)         do_create "$@" ;;
    reconfigure)    do_reconfigure "$@" ;;
    destroy)        do_destroy "$@" ;;
    list)           do_list ;;
    *)              echo "Unknown command: $COMMAND"; echo "Usage: $0 {prepare-config|create|reconfigure|destroy|list}"; exit 1 ;;
esac
