#!/bin/bash
set -euo pipefail

# Manage docketworks instances.
# Usage: instance.sh prepare-config <client> <env>
#        instance.sh create <client> <env> [--seed] [--fqdn <hostname>] [--no-start]
#        instance.sh destroy <client> <env>
#        instance.sh list
#
# --no-start: create the instance but do NOT enable/restart scheduler-* and
# celery-worker-* services, and drop a .dr-mode marker in the instance dir.
# This is the "cold standby" / DR mode: scheduler+celery would otherwise fire
# their first heartbeat (and hit Xero with live tokens) within ~5 min of
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

# Escape special chars for sed replacement strings (handles / & \ in values)
sed_escape() { printf '%s\n' "$1" | sed 's/[&/|\\\"]/\\&/g'; }

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

    mkdir -p "$CONFIG_DIR"
    sed "s|__INSTANCE__|$INSTANCE|g" "$TEMPLATE_DIR/credentials-instance.template" \
        > "$CREDS_FILE"
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

# ============================================================
# create
# ============================================================
do_create() {
    parse_client_env "$@"
    shift 2

    local SEED=false
    local CUSTOM_FQDN=""
    local NO_START=false
    local parsed
    if ! parsed=$(getopt -o '' --long seed,fqdn:,no-start -n "$(basename "$0") create" -- "$@"); then
        echo "Usage: $(basename "$0") create <client> <env> [--seed] [--fqdn <hostname>] [--no-start]" >&2
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
        echo "ERROR: Unexpected arguments to 'create': $*" >&2
        exit 1
    fi

    # --- Read instance credentials file ---
    local CREDS_FILE="$CONFIG_DIR/$INSTANCE.credentials.env"
    if [[ ! -f "$CREDS_FILE" ]]; then
        echo "ERROR: No credentials file found at $CREDS_FILE"
        echo ""
        echo "Run prepare-config first:"
        echo "  sudo $0 prepare-config $CLIENT $ENV"
        exit 1
    fi

    # Safe: edited only by the sysadmin who already has root access to run this script
    set -a
    source "$CREDS_FILE"
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

    if [[ ${#MISSING[@]} -gt 0 ]]; then
        echo "ERROR: Missing required values in $CREDS_FILE:"
        for var in "${MISSING[@]}"; do
            echo "  - $var"
        done
        exit 1
    fi

    # Validate GCP credentials file exists at the path provided
    if [[ ! -f "$GCP_CREDENTIALS" ]]; then
        echo "ERROR: GCP_CREDENTIALS file not found: $GCP_CREDENTIALS"
        echo "  Provide a valid path to a GCP service account JSON key in $CREDS_FILE"
        exit 1
    fi

    local INSTANCE_DIR="$INSTANCES_DIR/$INSTANCE"
    local INSTANCE_USER
    INSTANCE_USER="$(instance_user "$INSTANCE")"
    local DB_NAME="dw_${CLIENT}_${ENV}"
    local DB_USER="dw_${CLIENT}_${ENV}"
    local SCRUB_DB_NAME="dw_${CLIENT}_${ENV}_scrub"
    local TEST_DB_USER="dw_${CLIENT}_${ENV}_test"
    local TEST_DB_NAME="test_dw_${CLIENT}_${ENV}"

    log "=========================================="
    log "Creating docketworks instance: $INSTANCE"
    log "  Client:    $CLIENT"
    log "  Env:       $ENV"
    log "  Directory: $INSTANCE_DIR (= git checkout)"
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

    # --- Create instance directory structure ---
    # Instance dir is 750 with group www-data so nginx can traverse to
    # mediafiles, frontend/dist, and gunicorn.sock.
    # .env and logs stay owner-only (dw_<client>_<env>:dw_<client>_<env>, 600/700).
    # Instance users have NO supplementary groups, so dw_acme_uat cannot
    # traverse dw_msm_uat's dir (not owner, not in www-data).
    # Derive FQDN and cert domain
    local FQDN CERT_DOMAIN
    if [[ -n "$CUSTOM_FQDN" ]]; then
        FQDN="$CUSTOM_FQDN"
        CERT_DOMAIN="$CUSTOM_FQDN"
    else
        FQDN="${INSTANCE}.${DOMAIN}"
        CERT_DOMAIN="$DOMAIN"
    fi

    log "Creating instance directory structure..."
    mkdir -p "$INSTANCE_DIR"/{logs,mediafiles,dropbox}
    chown -R "$INSTANCE_USER:www-data" "$INSTANCE_DIR"
    chmod 750 "$INSTANCE_DIR"
    chmod 700 "$INSTANCE_DIR/logs"
    chmod 700 "$INSTANCE_DIR/dropbox"
    # Lock down credentials file — not needed by www-data
    chmod 600 "$CREDS_FILE"
    chown "$INSTANCE_USER:$INSTANCE_USER" "$CREDS_FILE"
    # Copy GCP service account key into instance dir with restricted perms
    cp "$GCP_CREDENTIALS" "$INSTANCE_DIR/gcp-credentials.json"
    chown "$INSTANCE_USER:$INSTANCE_USER" "$INSTANCE_DIR/gcp-credentials.json"
    chmod 600 "$INSTANCE_DIR/gcp-credentials.json"
    echo "$FQDN" > "$INSTANCE_DIR/.fqdn"
    chown "$INSTANCE_USER:$INSTANCE_USER" "$INSTANCE_DIR/.fqdn"
    # Symlink shared venv into instance dir so the user can `source ~/.venv/bin/activate`
    ln -sfn "$SHARED_VENV" "$INSTANCE_DIR/.venv"
    # Create .bash_profile that activates venv and loads .env.
    # .bash_profile (not .bashrc) because SSH login shells read .bash_profile.
    # The home dir IS the git checkout, so no cd needed.
    cat > "$INSTANCE_DIR/.bash_profile" <<'BASH_PROFILE'
source ~/.venv/bin/activate
set -a; source ~/.env; set +a
BASH_PROFILE
    chown "$INSTANCE_USER:$INSTANCE_USER" "$INSTANCE_DIR/.bash_profile"
    chmod 644 "$INSTANCE_DIR/.bash_profile"

    # --- Generate .env (skip if it already exists) ---
    if [[ -f "$INSTANCE_DIR/.env" ]]; then
        log ".env already exists — skipping (credentials preserved)."
    else
        local DB_PASSWORD TEST_DB_PASSWORD SECRET_KEY BEARER_SECRET
        DB_PASSWORD="$(openssl rand -base64 24 | tr -d '/+=' | head -c 32)"
        TEST_DB_PASSWORD="$(openssl rand -base64 24 | tr -d '/+=' | head -c 32)"
        SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(50))')"
        BEARER_SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(50))')"

        log "Generating .env from template..."
        # Escape sed-special chars in values that come from human-edited credentials.env
        local ESC_XERO_DEFAULT_USER_ID
        ESC_XERO_DEFAULT_USER_ID="$(sed_escape "$XERO_DEFAULT_USER_ID")"
        local ESC_EMAIL_HOST_USER ESC_EMAIL_HOST_PASSWORD ESC_DJANGO_ADMINS ESC_EMAIL_BCC
        ESC_EMAIL_HOST_USER="$(sed_escape "$EMAIL_HOST_USER")"
        ESC_EMAIL_HOST_PASSWORD="$(sed_escape "$EMAIL_HOST_PASSWORD")"
        ESC_DJANGO_ADMINS="$(sed_escape "$DJANGO_ADMINS")"
        ESC_EMAIL_BCC="$(sed_escape "$EMAIL_BCC")"

        local GCP_DEST="$INSTANCE_DIR/gcp-credentials.json"
        sed \
            -e "s|__INSTANCE__|$INSTANCE|g" \
            -e "s|__DOMAIN__|$DOMAIN|g" \
            -e "s|__FQDN__|$FQDN|g" \
            -e "s|__DB_NAME__|$DB_NAME|g" \
            -e "s|__DB_USER__|$DB_USER|g" \
            -e "s|__DB_PASSWORD__|$DB_PASSWORD|g" \
            -e "s|__SCRUB_DB_NAME__|$SCRUB_DB_NAME|g" \
            -e "s|__TEST_DB_USER__|$TEST_DB_USER|g" \
            -e "s|__TEST_DB_PASSWORD__|$TEST_DB_PASSWORD|g" \
            -e "s|__SECRET_KEY__|$SECRET_KEY|g" \
            -e "s|__BEARER_SECRET__|$BEARER_SECRET|g" \
            -e "s|__XERO_DEFAULT_USER_ID__|$ESC_XERO_DEFAULT_USER_ID|g" \
            -e "s|__GCP_CREDENTIALS_PATH__|$GCP_DEST|g" \
            -e "s|__EMAIL_HOST_USER__|$ESC_EMAIL_HOST_USER|g" \
            -e "s|__EMAIL_HOST_PASSWORD__|$ESC_EMAIL_HOST_PASSWORD|g" \
            -e "s|__DJANGO_ADMINS__|$ESC_DJANGO_ADMINS|g" \
            -e "s|__EMAIL_BCC__|$ESC_EMAIL_BCC|g" \
            "$TEMPLATE_DIR/env-instance.template" > "$INSTANCE_DIR/.env"

        # Append shared config: Google credentials (base-setup must have run first)
        local SHARED_ENV="$BASE_DIR/shared.env"
        if [[ ! -f "$SHARED_ENV" ]]; then
            echo "ERROR: $SHARED_ENV not found. Run server-setup.sh first."
            exit 1
        fi
        echo "" >> "$INSTANCE_DIR/.env"
        grep '^GOOGLE_MAPS_API_KEY=' "$SHARED_ENV" >> "$INSTANCE_DIR/.env"
        log "  Appended Google Maps API key from $SHARED_ENV"
        chown "$INSTANCE_USER:$INSTANCE_USER" "$INSTANCE_DIR/.env"
        chmod 600 "$INSTANCE_DIR/.env"
    fi

    # --- Ensure databases and DB users exist (always, even if .env was preserved) ---
    # Two roles per tenant, each owning only its own DB(s):
    #   $DB_USER      → $DB_NAME (app), $SCRUB_DB_NAME (backport scrubber)
    #   $TEST_DB_USER → $TEST_DB_NAME (pytest)
    # Test role has no CREATEDB; the test DB is pre-provisioned here so pytest
    # never needs cluster-level privileges. Keeping it separate from $DB_USER
    # means a misconfigured pytest run cannot reach the app DB.
    local DB_PASSWORD TEST_DB_PASSWORD
    DB_PASSWORD="$(. "$INSTANCE_DIR/.env" && echo "$DB_PASSWORD")"
    TEST_DB_PASSWORD="$(. "$INSTANCE_DIR/.env" && echo "$TEST_DB_PASSWORD")"
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

    # --- Clone repo directly into instance dir (instance dir = git checkout) ---
    if [[ -d "$INSTANCE_DIR/.git" ]]; then
        log "Code already cloned — pulling latest on main..."
        sudo -u "$INSTANCE_USER" git -C "$INSTANCE_DIR" remote set-url origin "$LOCAL_REPO"
        sudo -u "$INSTANCE_USER" git -C "$INSTANCE_DIR" fetch origin
        sudo -u "$INSTANCE_USER" git -C "$INSTANCE_DIR" checkout main
        sudo -u "$INSTANCE_USER" git -C "$INSTANCE_DIR" pull --ff-only
    else
        log "Initialising codebase in $INSTANCE_DIR from local repo (branch: main)..."
        sudo -u "$INSTANCE_USER" git -C "$INSTANCE_DIR" init -b main
        sudo -u "$INSTANCE_USER" git -C "$INSTANCE_DIR" remote add origin "$LOCAL_REPO"
        sudo -u "$INSTANCE_USER" git -C "$INSTANCE_DIR" fetch origin
        sudo -u "$INSTANCE_USER" git -C "$INSTANCE_DIR" checkout -f main
    fi

    # --- Generate frontend/.env (skip if it already exists) ---
    local FRONTEND_ENV="$INSTANCE_DIR/frontend/.env"
    if [[ -f "$FRONTEND_ENV" ]]; then
        log "frontend/.env already exists — skipping (credentials preserved)."
    else
        log "Generating frontend/.env from template..."
        local ESC_E2E_TEST_USERNAME ESC_E2E_TEST_PASSWORD ESC_XERO_USERNAME ESC_XERO_PASSWORD
        ESC_E2E_TEST_USERNAME="$(sed_escape "$E2E_TEST_USERNAME")"
        ESC_E2E_TEST_PASSWORD="$(sed_escape "$E2E_TEST_PASSWORD")"
        ESC_XERO_USERNAME="$(sed_escape "$XERO_USERNAME")"
        ESC_XERO_PASSWORD="$(sed_escape "$XERO_PASSWORD")"
        sed \
            -e "s|__INSTANCE__|$INSTANCE|g" \
            -e "s|__CLIENT__|$CLIENT|g" \
            -e "s|__DOMAIN__|$DOMAIN|g" \
            -e "s|__E2E_TEST_USERNAME__|$ESC_E2E_TEST_USERNAME|g" \
            -e "s|__E2E_TEST_PASSWORD__|$ESC_E2E_TEST_PASSWORD|g" \
            -e "s|__XERO_USERNAME__|$ESC_XERO_USERNAME|g" \
            -e "s|__XERO_PASSWORD__|$ESC_XERO_PASSWORD|g" \
            "$TEMPLATE_DIR/frontend-env-instance.template" > "$FRONTEND_ENV"
        chown "$INSTANCE_USER:$INSTANCE_USER" "$FRONTEND_ENV"
        chmod 600 "$FRONTEND_ENV"
    fi

    # --- Build frontend ---
    log "Building frontend for instance $INSTANCE..."
    sudo -u "$INSTANCE_USER" bash -c "
        cd '$INSTANCE_DIR/frontend'
        npm run build
        npm run manual:build
    "

    # --- Generate AI providers fixture from template ---
    log "Generating AI providers fixture..."
    local ESC_ANTHROPIC_API_KEY ESC_GEMINI_API_KEY ESC_MISTRAL_API_KEY
    ESC_ANTHROPIC_API_KEY="$(sed_escape "$ANTHROPIC_API_KEY")"
    ESC_GEMINI_API_KEY="$(sed_escape "$GEMINI_API_KEY")"
    ESC_MISTRAL_API_KEY="$(sed_escape "$MISTRAL_API_KEY")"
    sed \
        -e "s|__ANTHROPIC_API_KEY__|$ESC_ANTHROPIC_API_KEY|g" \
        -e "s|__GEMINI_API_KEY__|$ESC_GEMINI_API_KEY|g" \
        -e "s|__MISTRAL_API_KEY__|$ESC_MISTRAL_API_KEY|g" \
        "$TEMPLATE_DIR/ai-providers.json.template" \
        > "$INSTANCE_DIR/apps/workflow/fixtures/ai_providers.json"
    chown "$INSTANCE_USER:$INSTANCE_USER" "$INSTANCE_DIR/apps/workflow/fixtures/ai_providers.json"
    chmod 600 "$INSTANCE_DIR/apps/workflow/fixtures/ai_providers.json"

    # --- Run Django commands as instance user ---
    log "Running Django migrate..."
    "$SCRIPT_DIR/dw-run.sh" "$INSTANCE" python manage.py migrate --no-input

    # --- Load AI providers ---
    log "Loading AI providers..."
    "$SCRIPT_DIR/dw-run.sh" "$INSTANCE" python manage.py loaddata apps/workflow/fixtures/ai_providers.json

    # Remove the fixture after loading — keys live in the DB now, and the
    # file is a loaddata time-bomb (restore-prod-to-nonprod runs loaddata on
    # it, which would overwrite real DB keys with whatever is on disk).
    rm -f "$INSTANCE_DIR/apps/workflow/fixtures/ai_providers.json"

    # --- Create initial admin user ---
    log "Creating initial admin user..."
    "$SCRIPT_DIR/dw-run.sh" "$INSTANCE" python scripts/setup_dev_logins.py

    # --- Optionally seed data ---
    if [[ "$SEED" == "true" ]]; then
        log "Loading demo fixtures..."
        "$SCRIPT_DIR/dw-run.sh" "$INSTANCE" python manage.py loaddata demo_fixtures
    fi

    # --- DR-mode marker ---
    # If --no-start was passed, drop a marker file BEFORE the systemd installs
    # below so the marker check skips enable/restart for scheduler+celery in
    # this run, and so subsequent deploy.sh runs also leave them alone. The
    # unit files themselves are still rendered — "go live" later is just
    # `rm .dr-mode && systemctl enable --now scheduler-* celery-worker-*`.
    if [[ "$NO_START" == "true" ]]; then
        log "DR mode: writing $INSTANCE_DIR/.dr-mode (scheduler+celery will not be auto-started)"
        touch "$INSTANCE_DIR/.dr-mode"
        chown "$INSTANCE_USER:$INSTANCE_USER" "$INSTANCE_DIR/.dr-mode"
        chmod 644 "$INSTANCE_DIR/.dr-mode"
    fi

    # --- Install systemd service ---
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

    log "Installing systemd service scheduler-$INSTANCE..."
    sed \
        -e "s|__INSTANCE__|$INSTANCE|g" \
        -e "s|__INSTANCE_USER__|$INSTANCE_USER|g" \
        "$TEMPLATE_DIR/scheduler-instance.service.template" \
        > "/etc/systemd/system/scheduler-$INSTANCE.service"
    systemctl daemon-reload
    if [[ -f "$INSTANCE_DIR/.dr-mode" ]]; then
        log "  DR mode: skipping enable/restart of scheduler-$INSTANCE"
    else
        systemctl enable "scheduler-$INSTANCE"
        systemctl restart "scheduler-$INSTANCE"
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

    # --- Install sudoers drop-in ---
    # Lets the instance user restart its own units without a password.
    # Render to a temp file, validate with visudo, then install atomically —
    # a malformed file in /etc/sudoers.d locks out sudo entirely.
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

    # --- Install Nginx server block ---
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

    # --- Summary ---
    log "=========================================="
    log "Instance '$INSTANCE' created successfully"
    log "  URL:        https://$FQDN"
    log "  Directory:  $INSTANCE_DIR (= git checkout)"
    log "  User:       $INSTANCE_USER"
    log "  Database:   $DB_NAME"
    log "  Service:    gunicorn-$INSTANCE"
    log "  Scheduler:  scheduler-$INSTANCE"
    log "=========================================="

    echo ""
    echo "  Instance is live at: https://$FQDN"
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
    local TEST_DB_NAME="test_dw_${CLIENT}_${ENV}"

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
    echo "    - Service:   scheduler-$INSTANCE"
    echo "    - Nginx:     docketworks-$INSTANCE"
    echo ""
    read -p "Are you sure? (yes/no): " CONFIRM
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

    if systemctl is-active --quiet "scheduler-$INSTANCE" 2>/dev/null; then
        echo "=== Stopping Scheduler service ==="
        systemctl stop "scheduler-$INSTANCE"
    fi
    if [[ -f "/etc/systemd/system/scheduler-$INSTANCE.service" ]]; then
        echo "=== Removing Scheduler service ==="
        systemctl disable "scheduler-$INSTANCE" 2>/dev/null || true
        rm -f "/etc/systemd/system/scheduler-$INSTANCE.service"
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

    printf "%-15s %-12s %-12s %-20s %-40s\n" "INSTANCE" "GUNICORN" "SCHEDULER" "BRANCH" "URL"
    printf "%-15s %-12s %-12s %-20s %-40s\n" "--------" "--------" "---------" "------" "---"

    for name in "${INSTANCES[@]}"; do
        local status sched_status branch
        if systemctl is-active --quiet "gunicorn-$name" 2>/dev/null; then
            status="running"
        elif systemctl is-enabled --quiet "gunicorn-$name" 2>/dev/null; then
            status="stopped"
        else
            status="no service"
        fi

        if systemctl is-active --quiet "scheduler-$name" 2>/dev/null; then
            sched_status="running"
        elif systemctl is-enabled --quiet "scheduler-$name" 2>/dev/null; then
            sched_status="stopped"
        else
            sched_status="no service"
        fi

        local inst_dir="$INSTANCES_DIR/$name"
        if [[ -d "$inst_dir/.git" ]]; then
            branch="$(git -C "$inst_dir" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")"
        else
            branch="no code"
        fi

        printf "%-15s %-12s %-12s %-20s %-40s\n" "$name" "$status" "$sched_status" "$branch" "https://$(get_fqdn "$name")"
    done
}

# ============================================================
# main
# ============================================================
if [[ $# -lt 1 ]]; then
    echo "Usage: $0 {prepare-config|create|destroy|list} [args...]"
    echo "  prepare-config <client> <env>    — scaffold credentials file"
    echo "  create         <client> <env> [--seed]"
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
    destroy)        do_destroy "$@" ;;
    list)           do_list ;;
    *)              echo "Unknown command: $COMMAND"; echo "Usage: $0 {prepare-config|create|destroy|list}"; exit 1 ;;
esac
