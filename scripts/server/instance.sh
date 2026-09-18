#!/bin/bash
set -euo pipefail

# Manage docketworks instances.
# Usage: instance.sh prepare-config <client> <env> [--seed]
#        instance.sh create <client> <env> [--ref <ref>] [--allow-prod-ref] [--fqdn <hostname>] [--alias <hostname>]... [--no-start]
#        instance.sh reconfigure <client> <env> [--fqdn <hostname>] [--alias <hostname>]... [--no-alias] [--no-start]
#        instance.sh validate-config <client> <env>
#        instance.sh load-db-fixtures <client> <env>
#        instance.sh destroy <client> <env>
#        instance.sh stop <client> <env>
#        instance.sh start <client> <env>
#        instance.sh rehearse <client> [--ref <ref>]
#        instance.sh status <client> <env>
#        instance.sh history <client> <env>
#        instance.sh list
#
# --ref: on create only, the git ref this instance tracks (default
# origin/production). Re-point an existing instance with deploy.sh --ref.
#
# --alias: a further hostname the instance answers on (repeatable), on top of
# the canonical --fqdn. Same semantics as server-setup.sh --cert-domain: an
# explicit list replaces the persisted one (.aliases), --no-alias clears it,
# neither keeps it. Each hostname gets its own nginx server block and needs
# its own certificate (server-setup.sh --cert-domain); the app's outbound
# links and the Xero redirect URI stay on the canonical FQDN.
#
# --no-start: create the instance but do NOT enable/restart celery-beat-* and
# celery-worker-* services, and drop a .dr-mode marker in the instance dir.
# This is the "cold standby" / DR mode: celery-beat+celery-worker would otherwise
# fire their first heartbeat (and hit Xero with live tokens) within ~5 min of
# creation, which is the wrong posture for a standby that shares creds with a
# live primary. The marker also makes future deploy.sh runs leave the services
# alone. `stop` and `start` enter and leave the same state on a live instance:
# a tenant doing no work costs a running tenant's memory otherwise.
#
# Naming convention:
#   Instance name: <client>-<env>     (e.g., msm-uat)     — directory, systemd unit suffix
#   Database:      dw_<client>_<env>  (e.g., dw_msm_uat)
#   OS user:       dw_<client>_<env>  (e.g., dw_msm_uat)  — same string as the DB role
#   URL:           <client>-<env>.docketworks.site

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE_DIR="$SCRIPT_DIR/templates"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"
# shellcheck source=release-utils.sh
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
    shift 2

    local SEED=false
    local parsed
    if ! parsed=$(getopt -o '' --long seed -n "$(basename "$0") prepare-config" -- "$@"); then
        echo "Usage: $(basename "$0") prepare-config <client> <env> [--seed]" >&2
        exit 1
    fi
    eval set -- "$parsed"
    while true; do
        case "$1" in
            --seed) SEED=true; shift ;;
            --) shift; break ;;
        esac
    done
    if [[ $# -gt 0 ]]; then
        echo "ERROR: Unexpected arguments to 'prepare-config': $*" >&2
        exit 1
    fi

    local CREDS_FILE="$CONFIG_DIR/$INSTANCE.credentials.env"
    local COMPANY_DEFAULTS_FILE="$CONFIG_DIR/$INSTANCE.company-defaults.json"
    if [[ -e "$CREDS_FILE" || -e "$COMPANY_DEFAULTS_FILE" ]]; then
        echo "Instance configuration already exists:"
        echo "  $CREDS_FILE"
        echo "  $COMPANY_DEFAULTS_FILE"
        echo ""
        echo "Edit the existing files directly. prepare-config never overwrites them."
        exit 1
    fi

    ensure_config_dir
    sed "s|__INSTANCE__|$INSTANCE|g" "$TEMPLATE_DIR/credentials-instance.template" \
        > "$CREDS_FILE"
    if [[ "$SEED" == "true" ]]; then
        # company-defaults.json.template is a symlink to
        # apps/core/fixtures/company_defaults.json (the loadable demo fixture);
        # a second real copy under templates/ was rejected because nothing
        # would keep the two identical. cp dereferences the link.
        cp "$TEMPLATE_DIR/company-defaults.json.template" \
            "$COMPANY_DEFAULTS_FILE"
    else
        cp "$TEMPLATE_DIR/company-defaults-prospect.json.template" \
            "$COMPANY_DEFAULTS_FILE"
    fi
    chown root:root "$CREDS_FILE"
    chown root:root "$COMPANY_DEFAULTS_FILE"
    chmod 600 "$CREDS_FILE" "$COMPANY_DEFAULTS_FILE"

    echo ""
    echo "============================================================"
    echo "  Instance configuration created at:"
    echo "    $CREDS_FILE"
    echo "    $COMPANY_DEFAULTS_FILE"
    echo ""
    echo "  Fill out both files, then run:"
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

# Refuse any credential that could not have come from generate_password.
# These values are interpolated into SQL run as the postgres superuser, and
# they are read back from the instance-user-owned .env on every reconfigure:
# quoting alone was rejected because a value containing $$ terminates a
# dollar-quoted DO body and everything after it executes as the superuser.
require_safe_password() {
    local name="$1" value="$2"
    if [[ ! "$value" =~ ^[A-Za-z0-9]+$ ]]; then
        echo "ERROR: $name contains characters outside [A-Za-z0-9]." >&2
        echo "Generated credentials are always alphanumeric; a value that" >&2
        echo "is not was edited or injected. Refusing to pass it to SQL." >&2
        exit 1
    fi
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

    # The required list mirrors what v2 actually consumes: integration,
    # Xero-app and AI-provider fixtures (database rows), plus backups.
    # App-runtime settings come from .env.example's contract, not here.
    local MISSING=()
    [[ -z "${GCP_CREDENTIALS:-}" ]] && MISSING+=("GCP_CREDENTIALS")
    [[ -z "${BACKUP_GDRIVE_TEAM_DRIVE_ID:-}" ]] && MISSING+=("BACKUP_GDRIVE_TEAM_DRIVE_ID")
    [[ -z "${XERO_CLIENT_ID:-}" ]] && MISSING+=("XERO_CLIENT_ID")
    [[ -z "${XERO_CLIENT_SECRET:-}" ]] && MISSING+=("XERO_CLIENT_SECRET")
    [[ -z "${XERO_WEBHOOK_KEY:-}" ]] && MISSING+=("XERO_WEBHOOK_KEY")
    [[ -z "${XERO_REDIRECT_URI:-}" ]] && MISSING+=("XERO_REDIRECT_URI")
    [[ -z "${GOOGLE_MAPS_API_KEY:-}" ]] && MISSING+=("GOOGLE_MAPS_API_KEY")

    PHONE_PROVIDER_ENABLED="${PHONE_PROVIDER_ENABLED:-false}"
    PHONE_PROVIDER_RECORDING_DELETION_ENABLED="${PHONE_PROVIDER_RECORDING_DELETION_ENABLED:-false}"
    # The flags are written into JSON verbatim, so anything but the two JSON
    # literals is refused here rather than discovered by the loader.
    for flag in PHONE_PROVIDER_ENABLED PHONE_PROVIDER_RECORDING_DELETION_ENABLED; do
        case "${!flag}" in
            true|false) ;;
            *) echo "ERROR: $flag must be exactly 'true' or 'false' in $creds_file (got '${!flag}')"; exit 1 ;;
        esac
    done

    # Fable: enabled=true with an incomplete group would render nulls, the
    # loader would leave the row unset, and the verifier's disabled branch
    # would pass — a deliberately-enabled integration silently off. Enabling
    # the switch is what makes the group required (one-enabled-switch rule:
    # the flag gates, the values must then exist).
    if [[ "$PHONE_PROVIDER_ENABLED" == "true" ]]; then
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

# Pick this instance's Redis port (ADR 0065). Preserved from an existing .env
# that names a private port; otherwise the lowest port from 6380 that no
# neighbour's .env names and nothing is listening on. The shared port is
# never handed out: a .env found pointing there is what an instance had
# before it owned a Redis server, and is allocated afresh.
allocate_redis_port() {
    local env_file="$1"
    local existing port
    if [[ -n "$(read_env_value "$env_file" REDIS_URL)" ]]; then
        existing="$(redis_port_of_env "$env_file")" || return 1
        if [[ "$existing" != "$REDIS_SHARED_PORT" ]]; then
            printf '%s\n' "$existing"
            return 0
        fi
    fi

    local used=()
    local other_env
    for other_env in "$INSTANCES_DIR"/*/.env; do
        [[ -f "$other_env" && "$other_env" != "$env_file" ]] || continue
        port="$(redis_port_of_env "$other_env")" || return 1
        used+=("$port")
    done

    local candidate
    for candidate in $(seq 6380 6399); do
        if [[ " ${used[*]-} " == *" $candidate "* ]]; then
            continue
        fi
        # A listener no .env names (a stray redis, anything) would turn the
        # new unit into a bind crash loop; refuse the port here instead.
        if [[ -n "$(ss -ltnH "sport = :$candidate")" ]]; then
            continue
        fi
        printf '%s\n' "$candidate"
        return 0
    done
    echo "ERROR: No free Redis port left on this host (6380-6399); retire an instance." >&2
    return 1
}

render_instance_env() {
    local instance_dir="$1"
    local instance_user="$2"
    local db_name="$3"
    local db_user="$4"
    local scrub_db_name="$5"
    local test_db_user="$6"
    local fqdn="$7"
    local aliases_csv="$8"
    # True only for a rehearsal instance (ADR 0066): every unit, the
    # onboarding and the verification window then agree on the fake, and
    # no token minted for it can reach the real organisation from beat.
    local xero_fake="$9"

    local env_file="$instance_dir/.env"
    local db_password test_db_password secret_key jwt_signing_key
    local redis_port redis_password dropbox_workflow_folder
    db_password="$(read_env_value "$env_file" DB_PASSWORD)"
    test_db_password="$(read_env_value "$env_file" TEST_DB_PASSWORD)"
    secret_key="$(read_env_value "$env_file" SECRET_KEY)"
    jwt_signing_key="$(read_env_value "$env_file" JWT_SIGNING_KEY)"
    # Fable: read back like the credentials, not re-rendered: a Dropbox-
    # synced client points this at the synced workflow folder by hand, and
    # a reconfigure that reverted it to the empty instance dir would 404
    # every attachment (2026-08-31 production incident).
    dropbox_workflow_folder="$(read_env_value "$env_file" DROPBOX_WORKFLOW_FOLDER)"
    redis_port="$(allocate_redis_port "$env_file")"
    redis_password="$(redis_password_of_env "$env_file")"

    [[ -n "$db_password" ]] || db_password="$(generate_password)"
    [[ -n "$test_db_password" ]] || test_db_password="$(generate_password)"
    [[ -n "$redis_password" ]] || redis_password="$(generate_password)"
    # Interpolated into redis.conf and the URL by sed: the same alphabet rule
    # the SQL-bound passwords carry.
    require_safe_password "REDIS_URL password" "$redis_password"
    [[ -n "$secret_key" ]] || secret_key="$(generate_secret)"
    # Generated independently of SECRET_KEY: settings.py refuses to boot
    # when the two match, and rotating one must not rotate the other.
    [[ -n "$jwt_signing_key" ]] || jwt_signing_key="$(generate_secret)"
    [[ -n "$dropbox_workflow_folder" ]] ||
        dropbox_workflow_folder="$instance_dir/dropbox"

    local tmp_env
    tmp_env="$(mktemp "$instance_dir/.env.tmp.XXXXXX")"

    sed \
        -e "s|__INSTANCE__|$INSTANCE|g" \
        -e "s|__FQDN__|$fqdn|g" \
        -e "s|__APP_DOMAIN_ALIASES__|$aliases_csv|g" \
        -e "s|__DB_NAME__|$db_name|g" \
        -e "s|__DB_USER__|$db_user|g" \
        -e "s|__DB_PASSWORD__|$db_password|g" \
        -e "s|__SCRUB_DB_NAME__|$scrub_db_name|g" \
        -e "s|__TEST_DB_USER__|$test_db_user|g" \
        -e "s|__TEST_DB_PASSWORD__|$test_db_password|g" \
        -e "s|__SECRET_KEY__|$secret_key|g" \
        -e "s|__JWT_SIGNING_KEY__|$jwt_signing_key|g" \
        -e "s|__REDIS_PORT__|$redis_port|g" \
        -e "s|__REDIS_PASSWORD__|$redis_password|g" \
        -e "s|__XERO_FAKE__|$xero_fake|g" \
        -e "s|__DROPBOX_WORKFLOW_FOLDER__|$(sed_escape "$dropbox_workflow_folder")|g" \
        -e "s|__GCP_CREDENTIALS__|$(sed_escape "$instance_dir/gcp-credentials.json")|g" \
        "$TEMPLATE_DIR/env-instance.template" > "$tmp_env"

    chown "$instance_user:$instance_user" "$tmp_env"
    chmod 600 "$tmp_env"
    mv "$tmp_env" "$env_file"
}

# The instance's own Redis server (ADR 0065), from the port and password the
# freshly rendered .env carries. Always enabled and restarted, .dr-mode or
# not: it holds no vendor token and sends nothing, and a standby that goes
# live must find it running. Restarted rather than started because the conf
# may have changed; Requires= carries that restart to the runtime units,
# which are re-installed later in the same run anyway.
install_redis_unit() {
    local instance_dir="$1"
    local instance_user="$2"
    local env_file="$instance_dir/.env"
    local redis_dir="$instance_dir/redis"
    local port password tmp_conf
    port="$(redis_port_of_env "$env_file")"
    password="$(redis_password_of_env "$env_file")"

    log "Installing redis-$INSTANCE on 127.0.0.1:$port..."
    mkdir -p "$redis_dir"
    chown "$instance_user:$instance_user" "$redis_dir"
    chmod 700 "$redis_dir"
    tmp_conf="$(mktemp "$instance_dir/redis.conf.tmp.XXXXXX")"
    sed \
        -e "s|__INSTANCE__|$INSTANCE|g" \
        -e "s|__REDIS_PORT__|$port|g" \
        -e "s|__REDIS_PASSWORD__|$password|g" \
        "$TEMPLATE_DIR/redis-instance.conf.template" > "$tmp_conf"
    chown "$instance_user:$instance_user" "$tmp_conf"
    chmod 600 "$tmp_conf"
    mv "$tmp_conf" "$instance_dir/redis.conf"
    render_redis_unit "$INSTANCE" "$instance_user" "$TEMPLATE_DIR"
    systemctl daemon-reload
    systemctl enable "redis-$INSTANCE"
    systemctl restart "redis-$INSTANCE"
}

render_ai_providers_fixture() {
    local instance_dir="$1"
    local instance_user="$2"
    local fixture_dir="$instance_dir/.fixtures"

    log "Generating AI providers fixture..."
    mkdir -p "$fixture_dir"
    local OPENAI_API_KEY_JSON OPENAI_MODEL_NAME_JSON ANTHROPIC_API_KEY_JSON GEMINI_API_KEY_JSON MISTRAL_API_KEY_JSON
    OPENAI_API_KEY_JSON="$(sed_escape "$(json_string_or_null "${OPENAI_API_KEY:-}")")"
    OPENAI_MODEL_NAME_JSON="$(sed_escape "$(json_string_or_null "${OPENAI_MODEL_NAME:-}")")"
    ANTHROPIC_API_KEY_JSON="$(sed_escape "$(json_string_or_null "${ANTHROPIC_API_KEY:-}")")"
    GEMINI_API_KEY_JSON="$(sed_escape "$(json_string_or_null "${GEMINI_API_KEY:-}")")"
    MISTRAL_API_KEY_JSON="$(sed_escape "$(json_string_or_null "${MISTRAL_API_KEY:-}")")"
    local OPENAI_DEFAULT_ENABLED=false CLAUDE_DEFAULT_ENABLED=false GEMINI_DEFAULT_ENABLED=false MISTRAL_DEFAULT_ENABLED=false
    case "${AI_DEFAULT_PROVIDER:-}" in
        OpenAI) OPENAI_DEFAULT_ENABLED=true ;;
        Claude) CLAUDE_DEFAULT_ENABLED=true ;;
        Gemini) GEMINI_DEFAULT_ENABLED=true ;;
        Mistral) MISTRAL_DEFAULT_ENABLED=true ;;
        "") ;;
        *) echo "ERROR: Unknown AI_DEFAULT_PROVIDER"; return 1 ;;
    esac
    sed \
        -e "s|__OPENAI_API_KEY_JSON__|$OPENAI_API_KEY_JSON|g" \
        -e "s|__OPENAI_MODEL_NAME_JSON__|$OPENAI_MODEL_NAME_JSON|g" \
        -e "s|__ANTHROPIC_API_KEY_JSON__|$ANTHROPIC_API_KEY_JSON|g" \
        -e "s|__GEMINI_API_KEY_JSON__|$GEMINI_API_KEY_JSON|g" \
        -e "s|__MISTRAL_API_KEY_JSON__|$MISTRAL_API_KEY_JSON|g" \
        -e "s|__OPENAI_DEFAULT_ENABLED__|$OPENAI_DEFAULT_ENABLED|g" \
        -e "s|__CLAUDE_DEFAULT_ENABLED__|$CLAUDE_DEFAULT_ENABLED|g" \
        -e "s|__GEMINI_DEFAULT_ENABLED__|$GEMINI_DEFAULT_ENABLED|g" \
        -e "s|__MISTRAL_DEFAULT_ENABLED__|$MISTRAL_DEFAULT_ENABLED|g" \
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

render_integration_settings_fixture() {
    local instance_dir="$1"
    local instance_user="$2"
    local fixture_dir="$instance_dir/.fixtures"

    log "Generating integration settings fixture..."
    mkdir -p "$fixture_dir"
    local CHATKIT_DOMAIN_KEY_JSON GOOGLE_MAPS_API_KEY_JSON PHONE_PROVIDER_BASE_URL_JSON PHONE_PROVIDER_USERNAME_JSON
    local PHONE_PROVIDER_PASSWORD_JSON PHONE_PROVIDER_ACCOUNT_CODE_JSON
    CHATKIT_DOMAIN_KEY_JSON="$(sed_escape "$(json_string_or_null "${CHATKIT_DOMAIN_KEY:-}")")"
    GOOGLE_MAPS_API_KEY_JSON="$(sed_escape "$(json_string_or_null "${GOOGLE_MAPS_API_KEY:-}")")"
    PHONE_PROVIDER_BASE_URL_JSON="$(sed_escape "$(json_string_or_null "${PHONE_PROVIDER_BASE_URL:-}")")"
    PHONE_PROVIDER_USERNAME_JSON="$(sed_escape "$(json_string_or_null "${PHONE_PROVIDER_USERNAME:-}")")"
    PHONE_PROVIDER_PASSWORD_JSON="$(sed_escape "$(json_string_or_null "${PHONE_PROVIDER_PASSWORD:-}")")"
    PHONE_PROVIDER_ACCOUNT_CODE_JSON="$(sed_escape "$(json_string_or_null "${PHONE_PROVIDER_ACCOUNT_CODE:-}")")"
    sed \
        -e "s|__CHATKIT_DOMAIN_KEY_JSON__|$CHATKIT_DOMAIN_KEY_JSON|g" \
        -e "s|__GOOGLE_MAPS_API_KEY_JSON__|$GOOGLE_MAPS_API_KEY_JSON|g" \
        -e "s|__PHONE_PROVIDER_ENABLED__|${PHONE_PROVIDER_ENABLED:-false}|g" \
        -e "s|__PHONE_PROVIDER_RECORDING_DELETION_ENABLED__|${PHONE_PROVIDER_RECORDING_DELETION_ENABLED:-false}|g" \
        -e "s|__PHONE_PROVIDER_BASE_URL_JSON__|$PHONE_PROVIDER_BASE_URL_JSON|g" \
        -e "s|__PHONE_PROVIDER_USERNAME_JSON__|$PHONE_PROVIDER_USERNAME_JSON|g" \
        -e "s|__PHONE_PROVIDER_PASSWORD_JSON__|$PHONE_PROVIDER_PASSWORD_JSON|g" \
        -e "s|__PHONE_PROVIDER_ACCOUNT_CODE_JSON__|$PHONE_PROVIDER_ACCOUNT_CODE_JSON|g" \
        "$TEMPLATE_DIR/integration-settings.json.template" \
        > "$fixture_dir/integration_settings.json"
    chown -R "$instance_user:$instance_user" "$fixture_dir"
    chmod 700 "$fixture_dir"
    chmod 600 "$fixture_dir/integration_settings.json"
}

# ============================================================
# create / reconfigure
# ============================================================
# Load the credential-derived database rows: AI providers, Xero apps,
# integration settings. Requires the instance database to already carry
# every column load_integration_settings writes
# (crm_phoneprovidersettings.google_maps_api_key), which is why a release that
# adds a required credential runs reconfigure --skip-db-fixtures, then
# deploy.sh, then the load-db-fixtures subcommand (docs/server_setup.md)
# instead of loading from reconfigure before that release has migrated.
# Callers provide INSTANCE, INSTANCE_DIR, INSTANCE_USER and the sourced
# credentials (require_instance_credentials).
load_db_fixtures() {
    render_ai_providers_fixture "$INSTANCE_DIR" "$INSTANCE_USER"
    log "Loading AI providers..."
    local AI_PROVIDERS_FIXTURE="$INSTANCE_DIR/.fixtures/ai_providers.json"
    "$SCRIPT_DIR/dw-run.sh" "$INSTANCE" python manage.py load_ai_providers "$AI_PROVIDERS_FIXTURE" || {
        rm -f "$AI_PROVIDERS_FIXTURE"
        return 1
    }
    rm -f "$AI_PROVIDERS_FIXTURE"

    render_xero_apps_fixture "$INSTANCE_DIR" "$INSTANCE_USER"
    log "Loading Xero apps..."
    local XERO_APPS_FIXTURE="$INSTANCE_DIR/.fixtures/xero_apps.json"
    "$SCRIPT_DIR/dw-run.sh" "$INSTANCE" python manage.py shell -c \
        "from django.core.management import call_command; from apps.xero.models import XeroApp; print('XeroApp already configured; skipping xero_apps.json load') if XeroApp.objects.exists() else call_command('loaddata', '$XERO_APPS_FIXTURE')"
    rm -f "$XERO_APPS_FIXTURE"

    render_integration_settings_fixture "$INSTANCE_DIR" "$INSTANCE_USER"
    log "Loading integration settings..."
    local INTEGRATION_SETTINGS_FIXTURE="$INSTANCE_DIR/.fixtures/integration_settings.json"
    # Fable: not loaddata: the row holds several integrations, and a restored
    # instance that already carries the phone login must still receive the
    # Maps key without that login being overwritten. The command applies each
    # integration only while its columns are unset, and creates the row when a
    # scrubbed restore left the table empty.
    # The rendered fixture holds the key and the phone password; it is gone
    # whether the loader succeeds or not.
    "$SCRIPT_DIR/dw-run.sh" "$INSTANCE" python manage.py load_integration_settings \
        "$INTEGRATION_SETTINGS_FIXTURE" || {
        rm -f "$INTEGRATION_SETTINGS_FIXTURE"
        exit 1
    }
    rm -f "$INTEGRATION_SETTINGS_FIXTURE"
}

validate_company_defaults_config() {
    local config_file="$1"

    if [[ ! -f "$config_file" ]]; then
        echo "ERROR: No company defaults file found at $config_file" >&2
        echo "  Run prepare-config first, then complete the generated JSON." >&2
        exit 1
    fi
    require_root_owned_credentials_file "$config_file"
    python3 "$SCRIPT_DIR/validate_company_defaults.py" "$config_file"
}

ensure_instance_directories() {
    local instance_dir="$1"
    local instance_user="$2"

    mkdir -p "$instance_dir"/{logs,mediafiles,dropbox,phone-recordings,session-replays}
    chown "$instance_user:www-data" "$instance_dir"
    chmod 750 "$instance_dir"
    chown "$instance_user:$instance_user" "$instance_dir/logs" "$instance_dir/dropbox"
    chmod 700 "$instance_dir/logs"
    # Opus: dropbox is the client's Maestral sync root, and an external writer
    # (the office scanner) delivers into it, so it cannot be 700 like the
    # other instance-private directories. 700 was what shipped, and it cut
    # scanner delivery on msm-prod every time this ran while Maestral, systemd
    # and disk all reported healthy (KAN-360). The group is the instance's own,
    # so this widens nothing until an account is deliberately added to it;
    # setgid keeps the writer's files group-owned and readable by the app.
    chmod 2770 "$instance_dir/dropbox"
    chown "$instance_user:www-data" "$instance_dir/mediafiles"
    chmod 750 "$instance_dir/mediafiles"
    chown "$instance_user:$instance_user" \
        "$instance_dir/phone-recordings" \
        "$instance_dir/session-replays"
    chmod 700 "$instance_dir/phone-recordings" "$instance_dir/session-replays"
}

# Render one runtime unit and start it. `create` starts every unit; on a
# `reconfigure` a unit that was not running stays that way, because an
# operator mid-restore or a DR standby stopped it on purpose and a
# reconfigure that dispatched a Xero sync into a half-loaded database was how
# that was learned. `.dr-mode` never starts anything: docs/server_setup.md
# and deploy.sh both gate the units on it so the box accepts no traffic
# before DNS cutover, and "go live" is `instance.sh start`.
# Reads INSTANCE, INSTANCE_USER, INSTANCE_DIR and command_name from the
# caller (do_configure).
install_runtime_unit() {
    local unit="$1"
    local template="$2"
    local was_active=false
    systemctl is-active --quiet "$unit" 2>/dev/null && was_active=true

    log "Installing systemd service $unit..."
    sed \
        -e "s|__INSTANCE__|$INSTANCE|g" \
        -e "s|__INSTANCE_USER__|$INSTANCE_USER|g" \
        "$TEMPLATE_DIR/$template" \
        > "/etc/systemd/system/$unit.service"
    systemctl daemon-reload
    if [[ -f "$INSTANCE_DIR/.dr-mode" ]]; then
        log "  DR mode: skipping enable/restart of $unit"
    elif [[ "$command_name" != "create" && "$was_active" == "false" ]]; then
        log "  $unit was not running; left stopped (reconfigure keeps the operator's state)"
        systemctl enable "$unit"
    else
        systemctl enable "$unit"
        systemctl restart "$unit"
    fi
}

# The dir/user/database triple that means an instance exists in any degree:
# create refuses over it, and rehearse decides between a leftover its marker
# names and a neighbour it must never touch.
instance_state_exists() {
    local instance_dir="$1"
    local instance_user="$2"
    local db_name="$3"
    [[ -e "$instance_dir" ]] || id "$instance_user" &>/dev/null || \
        sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname = '$db_name'" | grep -q 1
}

do_configure() {
    local command_name="$1"
    shift
    local xero_fake="$1"
    shift

    parse_client_env "$@"
    shift 2

    # Seeding is decided at prepare-config time (--seed picks the seeded
    # company-defaults template); create/reconfigure take no --seed.
    local CUSTOM_FQDN=""
    local NO_START=false
    local REF="origin/production"
    local REF_SET=false
    local ALLOW_PROD_REF=false
    local SKIP_DB_FIXTURES=false
    local parsed
    local ALIASES=()
    local NO_ALIAS=false
    local long_opts="ref:,allow-prod-ref,fqdn:,alias:,no-alias,no-start,skip-db-fixtures"
    if ! parsed=$(getopt -o '' --long "$long_opts" -n "$(basename "$0") $command_name" -- "$@"); then
        if [[ "$command_name" == "create" ]]; then
            echo "Usage: $(basename "$0") $command_name <client> <env> [--ref <ref>] [--allow-prod-ref] [--fqdn <hostname>] [--alias <hostname>]... [--no-start]" >&2
        else
            echo "Usage: $(basename "$0") $command_name <client> <env> [--fqdn <hostname>] [--alias <hostname>]... [--no-alias] [--no-start] [--skip-db-fixtures]" >&2
        fi
        exit 1
    fi
    eval set -- "$parsed"
    while true; do
        case "$1" in
            --ref)      REF="$2"; REF_SET=true; shift 2 ;;
            --allow-prod-ref) ALLOW_PROD_REF=true; shift ;;
            --fqdn)     CUSTOM_FQDN="$2";       shift 2 ;;
            --alias)    ALIASES+=("$2");        shift 2 ;;
            --no-alias) NO_ALIAS=true;          shift ;;
            --no-start) NO_START=true;          shift ;;
            --skip-db-fixtures) SKIP_DB_FIXTURES=true; shift ;;
            --)         shift; break ;;
        esac
    done
    if [[ $# -gt 0 ]]; then
        echo "ERROR: Unexpected arguments to '$command_name': $*" >&2
        exit 1
    fi
    if [[ "$NO_ALIAS" == "true" && ${#ALIASES[@]} -gt 0 ]]; then
        echo "ERROR: --no-alias and --alias contradict each other." >&2
        exit 1
    fi
    if [[ "$REF_SET" == "true" && "$command_name" != "create" ]]; then
        echo "ERROR: '$command_name' does not accept --ref; use 'deploy.sh --ref' to re-point an existing instance." >&2
        exit 1
    fi
    if [[ "$SKIP_DB_FIXTURES" == "true" && "$command_name" == "create" ]]; then
        echo "ERROR: 'create' does not accept --skip-db-fixtures; a fresh instance needs its DB rows." >&2
        exit 1
    fi

    # One instance mutation at a time per host: the Redis port allocation
    # reads every neighbour's .env, so two concurrent runs could hand out
    # the same port.
    exec 8>"$BASE_DIR/.instance.lock"
    if ! flock -n 8; then
        echo "ERROR: another instance.sh create/reconfigure is already running." >&2
        exit 1
    fi

    local CREDS_FILE="$CONFIG_DIR/$INSTANCE.credentials.env"
    local COMPANY_DEFAULTS_FILE="$CONFIG_DIR/$INSTANCE.company-defaults.json"
    require_instance_credentials "$CREDS_FILE"
    validate_company_defaults_config "$COMPANY_DEFAULTS_FILE"

    local INSTANCE_DIR="$INSTANCES_DIR/$INSTANCE"
    local INSTANCE_USER
    INSTANCE_USER="$(instance_user "$INSTANCE")"
    local DB_NAME DB_USER SCRUB_DB_NAME TEST_DB_USER TEST_DB_NAME
    instance_db_names "$CLIENT" "$ENV"
    local IS_EXISTING=false
    local NEEDS_APP_BOOTSTRAP=false
    if [[ "$command_name" == "create" ]]; then
        if instance_state_exists "$INSTANCE_DIR" "$INSTANCE_USER" "$DB_NAME"; then
            echo "ERROR: Refusing to create over existing or partial instance state for $INSTANCE." >&2
            echo "  Use reconfigure for a complete instance, or destroy partial state first." >&2
            exit 1
        fi
        NEEDS_APP_BOOTSTRAP=true
    else
        IS_EXISTING=true
        if [[ ! -f "$INSTANCE_DIR/.env" || ( ! -L "$INSTANCE_DIR/app" && ! -L "$INSTANCE_DIR/current" ) ]]; then
            echo "ERROR: Cannot reconfigure incomplete instance $INSTANCE_DIR." >&2
            echo "  Use create for a new instance, or destroy partial state first." >&2
            exit 1
        fi
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

    local FQDN
    if [[ -n "$CUSTOM_FQDN" ]]; then
        FQDN="$CUSTOM_FQDN"
    elif [[ "$IS_EXISTING" == "true" && -f "$INSTANCE_DIR/.fqdn" ]]; then
        FQDN="$(head -n1 "$INSTANCE_DIR/.fqdn")"
    else
        FQDN="${INSTANCE}.${DOMAIN}"
    fi
    # An explicit list replaces the persisted one; --no-alias clears it;
    # neither keeps it.
    if [[ "$NO_ALIAS" == "false" && ${#ALIASES[@]} -eq 0 && -f "$INSTANCE_DIR/.aliases" ]]; then
        mapfile -t ALIASES < <(sed '/^[[:space:]]*$/d' "$INSTANCE_DIR/.aliases")
    fi
    local ALIASES_CSV
    ALIASES_CSV="$(IFS=,; echo "${ALIASES[*]}")"

    log "Ensuring instance directory structure..."
    ensure_instance_directories "$INSTANCE_DIR" "$INSTANCE_USER"
    ensure_instance_backup_dir "$INSTANCE" "$INSTANCE_USER"
    require_root_owned_credentials_file "$CREDS_FILE"
    # GCP_CREDENTIALS may legitimately point at the instance's own copy
    # (the documented fix when the original download path is gone) — cp
    # refuses same-file and would kill the run.
    if [[ "$(readlink -f "$GCP_CREDENTIALS")" != "$(readlink -f "$INSTANCE_DIR/gcp-credentials.json")" ]]; then
        cp "$GCP_CREDENTIALS" "$INSTANCE_DIR/gcp-credentials.json"
    fi
    chown "$INSTANCE_USER:$INSTANCE_USER" "$INSTANCE_DIR/gcp-credentials.json"
    chmod 600 "$INSTANCE_DIR/gcp-credentials.json"

    log "Writing rclone config for $INSTANCE to $(instance_rclone_config "$INSTANCE")..."
    write_instance_rclone_config \
        "$INSTANCE" \
        "$INSTANCE_USER" \
        "${BACKUP_GDRIVE_ROOT_FOLDER_ID:-}" \
        "${BACKUP_GDRIVE_TEAM_DRIVE_ID:-}"
    echo "$FQDN" > "$INSTANCE_DIR/.fqdn"
    printf '%s\n' "${ALIASES[@]}" > "$INSTANCE_DIR/.aliases"
    chown "$INSTANCE_USER:$INSTANCE_USER" "$INSTANCE_DIR/.fqdn" "$INSTANCE_DIR/.aliases"

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
        "$FQDN" \
        "$ALIASES_CSV" \
        "$xero_fake"
    # Before anything boots against the new .env: migrations, fixture loads
    # and the runtime units all reach the Redis it names.
    install_redis_unit "$INSTANCE_DIR" "$INSTANCE_USER"

    local DB_PASSWORD TEST_DB_PASSWORD
    DB_PASSWORD="$(read_env_value "$INSTANCE_DIR/.env" DB_PASSWORD)"
    TEST_DB_PASSWORD="$(read_env_value "$INSTANCE_DIR/.env" TEST_DB_PASSWORD)"
    require_safe_password DB_PASSWORD "$DB_PASSWORD"
    require_safe_password TEST_DB_PASSWORD "$TEST_DB_PASSWORD"
    log "Ensuring databases $DB_NAME, $SCRUB_DB_NAME and roles $DB_USER, $TEST_DB_USER exist..."
    sudo -u postgres psql <<EOSQL
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '$DB_USER') THEN
        CREATE ROLE "$DB_USER" WITH LOGIN PASSWORD '$DB_PASSWORD';
    ELSE
        ALTER ROLE "$DB_USER" WITH PASSWORD '$DB_PASSWORD';
    END IF;
END
\$\$;
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '$TEST_DB_USER') THEN
        CREATE ROLE "$TEST_DB_USER" WITH LOGIN PASSWORD '$TEST_DB_PASSWORD' CREATEDB;
    ELSE
        ALTER ROLE "$TEST_DB_USER" WITH LOGIN PASSWORD '$TEST_DB_PASSWORD' CREATEDB;
    END IF;
END
\$\$;
SELECT 'CREATE DATABASE "$DB_NAME" OWNER "$DB_USER"'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '$DB_NAME')\gexec
GRANT ALL PRIVILEGES ON DATABASE "$DB_NAME" TO "$DB_USER";
SELECT 'CREATE DATABASE "$SCRUB_DB_NAME" OWNER "$DB_USER"'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '$SCRUB_DB_NAME')\gexec
GRANT ALL PRIVILEGES ON DATABASE "$SCRUB_DB_NAME" TO "$DB_USER";
-- Cross-instance isolation (ADR 0048): a freshly created database carries
-- PUBLIC's implicit CONNECT+TEMP, so with pg_hba's 'local all all scram'
-- any neighbour instance's role could connect to this one's data. REVOKE
-- ALL (stronger than CONNECT alone: also drops TEMP and pre-PG15 CREATE)
-- and re-grant the owner explicitly. Idempotent, so reconfigure retrofits
-- pre-existing instances. The 'postgres' maintenance DB is deliberately
-- untouched: Django's test runner connects to it to CREATE/DROP the
-- per-tenant test databases.
REVOKE ALL ON DATABASE "$DB_NAME" FROM PUBLIC;
GRANT CONNECT ON DATABASE "$DB_NAME" TO "$DB_USER";
REVOKE ALL ON DATABASE "$SCRUB_DB_NAME" FROM PUBLIC;
GRANT CONNECT ON DATABASE "$SCRUB_DB_NAME" TO "$DB_USER";
EOSQL

    ensure_instance_app_link "$INSTANCE"
    if [[ ! -L "$INSTANCE_DIR/app" ]]; then
        local TARGET_SHA
        fetch_local_repo
        require_production_ref_or_ack "$INSTANCE" "$REF" "$ALLOW_PROD_REF"
        TARGET_SHA="$(resolve_release_ref "$REF")"
        log "Creating app release link: resolved $REF to $TARGET_SHA"
        ensure_release "$TARGET_SHA"
        switch_instance_release "$INSTANCE" "$TARGET_SHA"
        chown -h "$INSTANCE_USER:$INSTANCE_USER" "$INSTANCE_DIR/app"
    fi

    if [[ "$NEEDS_APP_BOOTSTRAP" == "true" ]]; then
        log "Running Django migrate..."
        "$SCRIPT_DIR/dw-run.sh" "$INSTANCE" python manage.py migrate --no-input
    fi

    if [[ "$NEEDS_APP_BOOTSTRAP" == "true" ]]; then
        log "Loading instance Company and CompanyDefaults..."
        local COMPANY_DEFAULTS_FIXTURE="$INSTANCE_DIR/.fixtures/company_defaults.json"
        mkdir -p "$INSTANCE_DIR/.fixtures"
        cp "$COMPANY_DEFAULTS_FILE" "$COMPANY_DEFAULTS_FIXTURE"
        chown -R "$INSTANCE_USER:$INSTANCE_USER" "$INSTANCE_DIR/.fixtures"
        chmod 700 "$INSTANCE_DIR/.fixtures"
        chmod 600 "$COMPANY_DEFAULTS_FIXTURE"
        "$SCRIPT_DIR/dw-run.sh" "$INSTANCE" python manage.py loaddata \
            "$COMPANY_DEFAULTS_FIXTURE"
        rm -f "$COMPANY_DEFAULTS_FIXTURE"
    fi

    if [[ "$SKIP_DB_FIXTURES" == "true" ]]; then
        # For a caller that reconfigures against a database the current
        # schema has not reached yet, and loads them itself afterwards with
        # `instance.sh load-db-fixtures`.
        log "Skipping credential-derived DB fixtures (--skip-db-fixtures)."
    else
        load_db_fixtures
    fi

    if [[ "$NEEDS_APP_BOOTSTRAP" == "true" ]]; then
        # No scripted admin bootstrap: a stored bootstrap password is a
        # liability, and instances restored from an existing database
        # already carry their staff. The operator creates the first login
        # interactively (printed in the summary below).
        ADMIN_NEXT_STEP=true
    fi

    if [[ "$NO_START" == "true" ]]; then
        log "DR mode: writing $INSTANCE_DIR/.dr-mode (celery-beat+celery-worker will not be auto-started)"
        touch "$INSTANCE_DIR/.dr-mode"
        chown "$INSTANCE_USER:$INSTANCE_USER" "$INSTANCE_DIR/.dr-mode"
        chmod 644 "$INSTANCE_DIR/.dr-mode"
    fi

    install_runtime_unit "gunicorn-$INSTANCE" gunicorn-instance.service.template
    install_runtime_unit "celery-beat-$INSTANCE" celery-beat-instance.service.template
    install_runtime_unit "celery-worker-$INSTANCE" celery-worker-instance.service.template

    log "Installing backup timers for $INSTANCE..."
    render_backup_units "$INSTANCE" "$INSTANCE_USER" "$TEMPLATE_DIR"
    systemctl daemon-reload
    systemctl enable --now "backup-db-$INSTANCE.timer"
    systemctl enable --now "backup-files-$INSTANCE.timer"
    log "  Enabled nightly backup timers backup-db-$INSTANCE.timer and backup-files-$INSTANCE.timer"

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

    log "Installing Nginx config for $FQDN${ALIASES_CSV:+ (aliases: $ALIASES_CSV)}..."
    render_instance_nginx "$INSTANCE"
    ln -sf "$NGINX_SITES_AVAILABLE/docketworks-$INSTANCE" "/etc/nginx/sites-enabled/"

    local host CERT_PATH MISSING_CERT=false
    for host in "$FQDN" "${ALIASES[@]}"; do
        CERT_PATH="/etc/letsencrypt/live/$(cert_live_dir "$host")/fullchain.pem"
        if [[ ! -f "$CERT_PATH" ]]; then
            log "  NOTE: no certificate for $host at $CERT_PATH — skipping nginx reload."
            log "  After DNS cutover: sudo scripts/server/server-setup.sh --cert-domain $host (docs/server_setup.md)"
            MISSING_CERT=true
        fi
    done
    if [[ "$MISSING_CERT" == "false" ]]; then
        nginx -t && systemctl reload nginx
    fi

    # The auth jails read the per-instance nginx access logs by glob; the
    # glob is evaluated when fail2ban (re)loads, so a new instance's log
    # is invisible until this reload.
    if systemctl is-active --quiet fail2ban; then
        log "Reloading fail2ban to pick up this instance's nginx access log..."
        systemctl reload fail2ban
    fi

    if [[ "$NEEDS_APP_BOOTSTRAP" == "true" ]]; then
        write_deploy_state \
            "$INSTANCE" "" "$TARGET_SHA" "$INSTANCE_USER" "$REF" "create"
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
    if [[ "${ADMIN_NEXT_STEP:-false}" == "true" ]]; then
        echo ""
        echo "  Next step — create the first login interactively (nothing stored on disk):"
        echo "    sudo $SCRIPT_DIR/dw-run.sh $INSTANCE python manage.py createsuperuser"
    fi
}

do_create() {
    do_configure create False "$@"
}

do_reconfigure() {
    do_configure reconfigure False "$@"
}

# ============================================================
# validate-config
# ============================================================
# The exact config checks create/reconfigure run before touching state,
# callable on their own. Read-only, so an operator can prove a later
# reconfigure will pass while the instance is still up, instead of
# discovering a missing credential after services are stopped and the
# release symlink is flipped.
do_validate_config() {
    parse_client_env "$@"
    require_instance_credentials "$CONFIG_DIR/$INSTANCE.credentials.env"
    # Validated in place: validate_company_defaults_config reports a missing
    # file itself, so there is nothing for this to check first.
    validate_company_defaults_config "$CONFIG_DIR/$INSTANCE.company-defaults.json"
    log "Config for $INSTANCE satisfies the contract."
}

# ============================================================
# load-db-fixtures
# ============================================================
# The credential-derived DB rows on their own, for a caller that ran
# reconfigure --skip-db-fixtures because the running release did not yet
# carry the loader the new fixtures need (docs/server_setup.md).
do_load_db_fixtures() {
    parse_client_env "$@"
    local INSTANCE_DIR="$INSTANCES_DIR/$INSTANCE"
    local INSTANCE_USER
    INSTANCE_USER="$(instance_user "$INSTANCE")"
    if [[ ! -f "$INSTANCE_DIR/.env" || ( ! -L "$INSTANCE_DIR/app" && ! -L "$INSTANCE_DIR/current" ) ]]; then
        echo "ERROR: $INSTANCE is not a complete instance (no .env or release link)." >&2
        exit 1
    fi
    require_instance_credentials "$CONFIG_DIR/$INSTANCE.credentials.env"
    load_db_fixtures
    log "Credential-derived DB rows loaded for $INSTANCE."
}

# ============================================================
# destroy
# ============================================================
do_destroy() {
    parse_client_env "$@"

    local INSTANCE_DIR="$INSTANCES_DIR/$INSTANCE"
    local INSTANCE_USER
    INSTANCE_USER="$(instance_user "$INSTANCE")"
    local DB_NAME DB_USER SCRUB_DB_NAME TEST_DB_USER TEST_DB_NAME
    instance_db_names "$CLIENT" "$ENV"

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
    echo "    - Service:   celery-worker-$INSTANCE"
    echo "    - Timers:    backup-db-$INSTANCE, backup-files-$INSTANCE"
    echo "    - Nginx:     docketworks-$INSTANCE"
    echo ""
    read -r -p "Are you sure? (yes/no): " CONFIRM
    if [[ "$CONFIRM" != "yes" ]]; then
        echo "Aborted."
        exit 0
    fi

    destroy_instance "$CLIENT" "$ENV"
}

# The removal itself, prompt-free. do_destroy asks first; rehearse calls it
# for the one instance its marker names. No confirmation-skipping flag
# exists: a flag would make every instance destroyable from a script, the
# marker makes exactly one.
destroy_instance() {
    local client="$1"
    local env="$2"
    local INSTANCE="${client}-${env}"
    local INSTANCE_DIR="$INSTANCES_DIR/$INSTANCE"
    local INSTANCE_USER
    INSTANCE_USER="$(instance_user "$INSTANCE")"
    local DB_NAME DB_USER SCRUB_DB_NAME TEST_DB_USER TEST_DB_NAME
    instance_db_names "$client" "$env"

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

    if systemctl is-active --quiet "celery-worker-$INSTANCE" 2>/dev/null; then
        echo "=== Stopping Celery Worker service ==="
        systemctl stop "celery-worker-$INSTANCE"
    fi
    if [[ -f "/etc/systemd/system/celery-worker-$INSTANCE.service" ]]; then
        echo "=== Removing Celery Worker service ==="
        systemctl disable "celery-worker-$INSTANCE" 2>/dev/null || true
        rm -f "/etc/systemd/system/celery-worker-$INSTANCE.service"
        systemctl daemon-reload
    fi
    # After its dependants: the instance dir removal below takes the conf
    # and the dump with it.
    if systemctl is-active --quiet "redis-$INSTANCE" 2>/dev/null; then
        echo "=== Stopping Redis service ==="
        systemctl stop "redis-$INSTANCE"
    fi
    if [[ -f "/etc/systemd/system/redis-$INSTANCE.service" ]]; then
        echo "=== Removing Redis service ==="
        systemctl disable "redis-$INSTANCE" 2>/dev/null || true
        rm -f "/etc/systemd/system/redis-$INSTANCE.service"
        systemctl daemon-reload
    fi
    if [[ -f "/etc/systemd/system/backup-db-$INSTANCE.timer" ]]; then
        echo "=== Removing Backup timer ==="
        systemctl stop "backup-db-$INSTANCE.timer" 2>/dev/null || true
        systemctl disable "backup-db-$INSTANCE.timer" 2>/dev/null || true
        rm -f "/etc/systemd/system/backup-db-$INSTANCE.timer"
        systemctl daemon-reload
    fi
    if [[ -f "/etc/systemd/system/backup-db-$INSTANCE.service" ]]; then
        echo "=== Removing Backup service ==="
        rm -f "/etc/systemd/system/backup-db-$INSTANCE.service"
        systemctl daemon-reload
    fi
    if [[ -f "/etc/systemd/system/backup-files-$INSTANCE.timer" ]]; then
        echo "=== Removing File Backup timer ==="
        systemctl stop "backup-files-$INSTANCE.timer" 2>/dev/null || true
        systemctl disable "backup-files-$INSTANCE.timer" 2>/dev/null || true
        rm -f "/etc/systemd/system/backup-files-$INSTANCE.timer"
        systemctl daemon-reload
    fi
    if [[ -f "/etc/systemd/system/backup-files-$INSTANCE.service" ]]; then
        echo "=== Removing File Backup service ==="
        rm -f "/etc/systemd/system/backup-files-$INSTANCE.service"
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
    # DROP DATABASE stays best-effort (|| true) so destroy proceeds past a
    # half-created instance, but DROP ROLE deliberately does not: set -e
    # surfaces its real failure. The rejected alternative was || true on
    # DROP ROLE plus a post-hoc pg_roles SELECT to catch leaks — but with
    # postgres down that SELECT prints nothing, its grep finds no leak, and
    # destroy exits 0 with both roles leaked: the verification defeated
    # itself in exactly the scenario it existed to catch.
    sudo -u postgres psql -c "DROP DATABASE IF EXISTS \"$DB_NAME\";" || true
    sudo -u postgres psql -c "DROP DATABASE IF EXISTS \"$SCRUB_DB_NAME\";" || true
    sudo -u postgres psql -c "DROP DATABASE IF EXISTS \"$TEST_DB_NAME\";" || true
    # DROP ROLE refuses while the role still owns any database, and both
    # roles can own strays beyond the canonical names dropped above: a
    # crashed or --reuse-db pytest run leaves per-worker clones
    # (${TEST_DB_NAME}_gw0, ...) owned by $TEST_DB_USER, and a leftover
    # backport artefact can be owned by $DB_USER. Sweep everything each
    # role owns before dropping it.
    local role leftover_db
    for role in "$DB_USER" "$TEST_DB_USER"; do
        while IFS= read -r leftover_db; do
            [[ -n "$leftover_db" ]] || continue
            sudo -u postgres psql -c "DROP DATABASE IF EXISTS \"$leftover_db\";" || true
        done < <(sudo -u postgres psql -tAc \
            "SELECT datname FROM pg_database WHERE pg_get_userbyid(datdba) = '$role'")
        sudo -u postgres psql -c "DROP ROLE IF EXISTS \"$role\";"
    done

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
# rehearse
# ============================================================
# ADR 0066 is the decision and its rules; docs/server_setup.md Part E is
# how it is run. Two facts live here because the code depends on them: the
# env is fixed to uat because create would accept prod and only
# verify-instance.sh would refuse it, after the instance existed; and the
# run is red at `connect` until the pieces named in
# apps/xero/fake/tests/test_every_call_is_routed.py land.
#
# The values the EXIT trap reports are deliberately not `local`: the trap
# runs after this function has returned.
# Idempotent: called before destroy removes the instance directory, and
# again by the trap for a run that never reached destroy.
rehearse_collect_artifacts() {
    local artifact
    for artifact in playwright-report test-results test-history; do
        if [[ -e "$INSTANCE_DIR/e2e/$artifact" && ! -e "$RUN_DIR/$artifact" ]]; then
            cp -a "$INSTANCE_DIR/e2e/$artifact" "$RUN_DIR/"
        fi
    done
}

rehearse_report() {
    local status=$?
    set +e
    rehearse_collect_artifacts
    local unit_state=destroyed
    if [[ "$STEP" != "done" && -d "$INSTANCE_DIR" ]]; then
        # Inspection needs the directory and the database, not the processes:
        # an idle instance holds ~2.5 GiB resident (measured 2026-09-17, the
        # same as one serving users, because the process shape is fixed) and
        # the host has no swap, so a red run left running is a tenant's worth
        # of memory until the next rehearsal.
        stop_instance "$INSTANCE"
        unit_state=stopped
    fi
    {
        echo "instance=$INSTANCE"
        echo "ref=$REF"
        echo "sha=$TARGET_SHA"
        echo "started=$STARTED"
        echo "duration_s=$SECONDS"
        echo "step_reached=$STEP"
        echo "exit=$status"
        echo "units=$unit_state"
    } > "$RUN_DIR/result.txt"
    if [[ "$STEP" == "done" ]]; then
        echo "REHEARSAL PASSED: $INSTANCE from $REF ($SHA8) created, onboarded, verified, destroyed — $RUN_DIR"
    else
        echo "REHEARSAL FAILED at $STEP (exit $status): $INSTANCE stopped and left for inspection; artifacts under $RUN_DIR" >&2
    fi
    exit "$status"
}

do_rehearse() {
    if [[ $# -lt 1 ]]; then
        echo "Usage: $0 rehearse <client> [--ref <ref>]" >&2
        exit 1
    fi
    parse_client_env "$1" uat
    shift
    REF="origin/main"
    local parsed
    if ! parsed=$(getopt -o '' --long ref: -n "$(basename "$0") rehearse" -- "$@"); then
        echo "Usage: $0 rehearse <client> [--ref <ref>]" >&2
        exit 1
    fi
    eval set -- "$parsed"
    while true; do
        case "$1" in
            --ref) REF="$2"; shift 2 ;;
            --)    shift; break ;;
        esac
    done
    if [[ $# -gt 0 ]]; then
        echo "ERROR: Unexpected arguments to 'rehearse': $*" >&2
        exit 1
    fi

    INSTANCE_DIR="$INSTANCES_DIR/$INSTANCE"
    local INSTANCE_USER
    INSTANCE_USER="$(instance_user "$INSTANCE")"
    local DB_NAME DB_USER SCRUB_DB_NAME TEST_DB_USER TEST_DB_NAME
    instance_db_names "$CLIENT" "$ENV"

    # All three before anything is mutated: the E2E user's credentials are
    # first read inside verify-instance.sh, which would otherwise refuse
    # with the instance already built.
    local file
    for file in "$INSTANCE.credentials.env" "$INSTANCE.company-defaults.json" "$INSTANCE.e2e.env"; do
        if [[ ! -f "$CONFIG_DIR/$file" ]]; then
            echo "ERROR: No $CONFIG_DIR/$file." >&2
            echo "  Run: sudo $0 prepare-config $CLIENT uat --seed, complete both files, and create" >&2
            echo "  $CONFIG_DIR/$INSTANCE.e2e.env (docs/server_setup.md, Part E)." >&2
            exit 1
        fi
        require_root_owned_credentials_file "$CONFIG_DIR/$file"
    done

    fetch_local_repo
    TARGET_SHA="$(resolve_release_ref "$REF")"
    SHA8="$(short_release_sha "$TARGET_SHA")"
    mkdir -p "$REHEARSALS_DIR"
    chmod 755 "$REHEARSALS_DIR"
    local marker="$REHEARSALS_DIR/.active"

    STEP=leftover
    if instance_state_exists "$INSTANCE_DIR" "$INSTANCE_USER" "$DB_NAME"; then
        if [[ -f "$marker" && "$(cat "$marker")" == "$INSTANCE" ]]; then
            log "Destroying $INSTANCE, left by the previous rehearsal..."
            destroy_instance "$CLIENT" "$ENV"
        else
            echo "ERROR: $INSTANCE exists and no rehearsal left it; refusing to destroy a neighbour." >&2
            echo "  If it is yours to remove: sudo $0 destroy $CLIENT uat" >&2
            exit 1
        fi
    fi
    # After the guard: a refused run has no report and leaves no directory.
    RUN_DIR="$REHEARSALS_DIR/$(date +%Y%m%d_%H%M%S)-$SHA8"
    mkdir "$RUN_DIR"
    echo "$INSTANCE" > "$marker"

    STARTED="$(date '+%Y-%m-%d %H:%M:%S')"
    SECONDS=0
    trap rehearse_report EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM

    STEP=create
    do_configure create True "$CLIENT" uat --ref "$REF"

    STEP=post-create-checks
    local check
    for check in check_company_defaults check_xero_app check_integration_settings; do
        "$SCRIPT_DIR/dw-run.sh" "$INSTANCE" python -m "scripts.ops.restore_checks.$check"
    done

    STEP=staff
    "$SCRIPT_DIR/dw-run.sh" "$INSTANCE" python manage.py loaddata apps/accounts/fixtures/initial_data.json

    log "Onboarding under the fake Xero: red at connect until the pieces named in apps/xero/fake/tests/test_every_call_is_routed.py land."
    STEP=connect
    "$SCRIPT_DIR/dw-run.sh" "$INSTANCE" python manage.py fake_xero_connect

    STEP=onboarding
    "$SCRIPT_DIR/dw-run.sh" "$INSTANCE" python manage.py finalize_instance_onboarding --seed-xero

    STEP=verify-e2e
    "$SCRIPT_DIR/verify-instance.sh" "$CLIENT" uat --e2e

    STEP=collect
    rehearse_collect_artifacts

    STEP=destroy
    destroy_instance "$CLIENT" uat
    rm -f "$marker"

    STEP="done"
    exit 0
}

# ============================================================
# list
# ============================================================
# ============================================================
# stop / start
# ============================================================
# A stopped instance keeps its directory, database, units and nginx site and
# runs nothing. The state is the .dr-mode marker that deploy.sh, rollback.sh,
# reconfigure and verify-instance.sh already honour (kept current, never
# started), so a tenant doing no work and a red rehearsal share one
# mechanism. Units are disabled as well as stopped, or a host reboot would
# start what an operator stopped. Redis goes too: its queue is the stopped
# instance's own and nothing consumes it. Backup timers keep running; a dump
# of an unchanged database is cheap and keeps the retention chain whole.
stop_instance() {
    local instance="$1"
    local instance_dir="$INSTANCES_DIR/$instance"
    local instance_user
    instance_user="$(instance_user "$instance")"
    local unit
    for unit in celery-beat celery-worker gunicorn redis; do
        log "  Stopping $unit-$instance"
        systemctl disable --now "$unit-$instance"
    done
    touch "$instance_dir/.dr-mode"
    chown "$instance_user:$instance_user" "$instance_dir/.dr-mode"
    chmod 644 "$instance_dir/.dr-mode"
}

require_complete_instance() {
    local instance="$1"
    local instance_dir="$INSTANCES_DIR/$instance"
    if [[ ! -f "$instance_dir/.env" || ! -L "$instance_dir/app" ]]; then
        echo "ERROR: $instance is not a complete instance on this host (no .env or release link)." >&2
        exit 1
    fi
}

do_stop() {
    parse_client_env "$@"
    require_complete_instance "$INSTANCE"
    log "Stopping $INSTANCE; deploys keep it current, and 'sudo $0 start $CLIENT $ENV' brings it back..."
    stop_instance "$INSTANCE"
    log "$INSTANCE stopped: https://$(head -n1 "$INSTANCES_DIR/$INSTANCE/.fqdn") answers 502 until it is started."
}

do_start() {
    parse_client_env "$@"
    require_complete_instance "$INSTANCE"
    rm -f "$INSTANCES_DIR/$INSTANCE/.dr-mode"
    local unit
    for unit in redis celery-worker celery-beat gunicorn; do
        log "  Starting $unit-$INSTANCE"
        systemctl enable --now "$unit-$INSTANCE"
    done
    log "$INSTANCE started: $(short_release_sha "$(instance_current_sha "$INSTANCE")") at https://$(head -n1 "$INSTANCES_DIR/$INSTANCE/.fqdn")"
}

do_status() {
    parse_client_env "$@"

    local running_sha
    running_sha="$(instance_current_sha "$INSTANCE")"
    if [[ -z "$running_sha" ]]; then
        echo "ERROR: $INSTANCE has no release (not built)." >&2
        exit 1
    fi

    fetch_local_repo
    local prod_sha main_sha
    prod_sha="$(resolve_release_ref origin/production 2>/dev/null || true)"
    main_sha="$(resolve_release_ref origin/main 2>/dev/null || true)"

    local match="candidate (matches no tracked ref)"
    if [[ -n "$prod_sha" && "$running_sha" == "$prod_sha" ]]; then
        match="== origin/production"
    elif [[ -n "$main_sha" && "$running_sha" == "$main_sha" ]]; then
        match="== origin/main (candidate)"
    fi

    echo "instance: $INSTANCE"
    local tracked_ref
    if tracked_ref="$(read_instance_deploy_ref "$INSTANCE" 2>/dev/null)"; then
        echo "  tracks:  $tracked_ref"
    else
        echo "  tracks:  NOT CONFIGURED"
    fi
    echo "  running: $(short_release_sha "$running_sha")  ($match)"
    if [[ -n "$prod_sha" ]]; then
        local behind ahead
        behind="$(sudo -u docketworks git -C "$LOCAL_REPO" rev-list --count "${running_sha}..${prod_sha}" 2>/dev/null || echo '?')"
        ahead="$(sudo -u docketworks git -C "$LOCAL_REPO" rev-list --count "${prod_sha}..${running_sha}" 2>/dev/null || echo '?')"
        echo "  vs origin/production: ${behind} behind, ${ahead} ahead"
    fi
}

do_history() {
    parse_client_env "$@"
    print_deploy_history "$INSTANCE"
}

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
        # A unit file that exists but is not active is "stopped" whether or not
        # it is enabled: `stop` disables so a reboot cannot undo it, and that
        # instance is stopped, not serviceless.
        if systemctl is-active --quiet "gunicorn-$name" 2>/dev/null; then
            status="running"
        elif [[ -f "/etc/systemd/system/gunicorn-$name.service" ]]; then
            status="stopped"
        else
            status="no service"
        fi

        if systemctl is-active --quiet "celery-beat-$name" 2>/dev/null; then
            sched_status="running"
        elif [[ -f "/etc/systemd/system/celery-beat-$name.service" ]]; then
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

        printf "%-15s %-12s %-12s %-10s %-40s\n" "$name" "$status" "$sched_status" "$sha" "https://$(instance_hostnames "$name" | head -n1)"
    done
}

# ============================================================
# main
# ============================================================
if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
    return 0
fi

if [[ $# -lt 1 ]]; then
    echo "Usage: $0 {prepare-config|create|reconfigure|validate-config|load-db-fixtures|destroy|stop|start|rehearse|status|history|list} [args...]"
    echo "  prepare-config   <client> <env> [--seed]"
    echo "  create           <client> <env> [--ref <ref>] [--allow-prod-ref] [--fqdn <hostname>] [--alias <hostname>]... [--no-alias] [--no-start]"
    echo "  reconfigure      <client> <env> [--fqdn <hostname>] [--alias <hostname>]... [--no-alias] [--no-start] [--skip-db-fixtures]"
    echo "  validate-config  <client> <env>"
    echo "  load-db-fixtures <client> <env>"
    echo "  destroy          <client> <env>"
    echo "  stop             <client> <env>"
    echo "  start            <client> <env>"
    echo "  rehearse         <client> [--ref <ref>]"
    echo "  status           <client> <env>"
    echo "  history          <client> <env>"
    echo "  list"
    exit 1
fi

COMMAND="$1"; shift

if [[ "$COMMAND" != "list" && $EUID -ne 0 ]]; then
    echo "ERROR: This script must be run as root (use sudo)."
    exit 1
fi

case "$COMMAND" in
    prepare-config)   do_prepare_config "$@" ;;
    create)           do_create "$@" ;;
    reconfigure)      do_reconfigure "$@" ;;
    validate-config)  do_validate_config "$@" ;;
    load-db-fixtures) do_load_db_fixtures "$@" ;;
    destroy)          do_destroy "$@" ;;
    stop)             do_stop "$@" ;;
    start)            do_start "$@" ;;
    rehearse)         do_rehearse "$@" ;;
    status)           do_status "$@" ;;
    history)          do_history "$@" ;;
    list)             do_list ;;
    *)                echo "Unknown command: $COMMAND"; echo "Usage: $0 {prepare-config|create|reconfigure|validate-config|load-db-fixtures|destroy|stop|start|rehearse|status|history|list}"; exit 1 ;;
esac
