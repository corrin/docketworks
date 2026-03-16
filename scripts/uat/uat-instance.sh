#!/bin/bash
set -euo pipefail

# Manage UAT/demo instances of docketworks.
# Usage: uat-instance.sh create <name> [--seed] [--branch <branch>]
#        uat-instance.sh destroy <name>
#        uat-instance.sh list

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TEMPLATE_DIR="$SCRIPT_DIR/templates"
source "$SCRIPT_DIR/uat-common.sh"

# ============================================================
# create
# ============================================================
do_create() {
    local INSTANCE="" SEED=false BRANCH="main"

    if [[ $# -lt 1 ]]; then
        echo "Usage: $0 create <instance-name> [--seed] [--branch <branch>]"
        exit 1
    fi

    INSTANCE="$1"; shift
    if [[ ! "$INSTANCE" =~ ^[a-z0-9][a-z0-9-]*$ ]]; then
        echo "ERROR: Instance name must be lowercase alphanumeric (hyphens allowed, cannot start with hyphen)."
        exit 1
    fi

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --seed) SEED=true; shift ;;
            --branch) BRANCH="$2"; shift 2 ;;
            *) echo "Unknown option: $1"; exit 1 ;;
        esac
    done

    local INSTANCE_DIR="$INSTANCES_DIR/$INSTANCE"
    local INSTANCE_USER="dw-$INSTANCE"
    local DB_NAME="docketworks_${INSTANCE//-/_}"
    local DB_USER="docketworks_${INSTANCE//-/_}"
    local CODE_DIR="$INSTANCE_DIR/code"

    log "=========================================="
    log "Creating docketworks instance: $INSTANCE"
    log "  Directory: $INSTANCE_DIR"
    log "  User:      $INSTANCE_USER"
    log "  Code:      $CODE_DIR (branch: $BRANCH)"
    log "  Database:  $DB_NAME"
    log "  URL:       https://$INSTANCE.$DOMAIN"
    log "=========================================="

    # --- Create per-instance OS user ---
    if id "$INSTANCE_USER" &>/dev/null; then
        log "User '$INSTANCE_USER' already exists, skipping."
    else
        log "Creating system user '$INSTANCE_USER'..."
        useradd --system --shell /bin/bash --no-create-home "$INSTANCE_USER"
        usermod -aG docketworks "$INSTANCE_USER"
        usermod -aG www-data "$INSTANCE_USER"
        log "  Created user '$INSTANCE_USER' (groups: docketworks, www-data)."
    fi

    # --- Create instance directory structure ---
    log "Creating instance directory structure..."
    mkdir -p "$INSTANCE_DIR"/{logs,mediafiles,staticfiles}
    chown -R "$INSTANCE_USER:$INSTANCE_USER" "$INSTANCE_DIR"
    chmod 700 "$INSTANCE_DIR"
    chmod 755 "$INSTANCE_DIR/staticfiles"

    # --- Generate credentials + DB + .env (skip all if .env exists) ---
    if [[ -f "$INSTANCE_DIR/.env" ]]; then
        log ".env already exists — skipping (credentials preserved)."
    else
        local DB_PASSWORD SECRET_KEY
        DB_PASSWORD="$(openssl rand -base64 24 | tr -d '/+=' | head -c 32)"
        SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(50))')"

        log "Creating database $DB_NAME and user $DB_USER (if not exists)..."
        mysql -u root <<EOSQL
CREATE DATABASE IF NOT EXISTS \`$DB_NAME\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS '$DB_USER'@'localhost' IDENTIFIED BY '$DB_PASSWORD';
GRANT ALL PRIVILEGES ON \`$DB_NAME\`.* TO '$DB_USER'@'localhost';
FLUSH PRIVILEGES;
EOSQL

        log "Generating .env from template..."
        sed \
            -e "s/__INSTANCE__/$INSTANCE/g" \
            -e "s/__DOMAIN__/$DOMAIN/g" \
            -e "s/__DB_NAME__/$DB_NAME/g" \
            -e "s/__DB_USER__/$DB_USER/g" \
            -e "s/__DB_PASSWORD__/$DB_PASSWORD/g" \
            -e "s/__SECRET_KEY__/$SECRET_KEY/g" \
            -e "s/__XERO_CLIENT_ID__/REPLACE_ME/g" \
            -e "s/__XERO_CLIENT_SECRET__/REPLACE_ME/g" \
            -e "s/__EMAIL_USER__/REPLACE_ME/g" \
            -e "s/__EMAIL_PASSWORD__/REPLACE_ME/g" \
            "$TEMPLATE_DIR/env-instance.template" > "$INSTANCE_DIR/.env"
        chown "$INSTANCE_USER:$INSTANCE_USER" "$INSTANCE_DIR/.env"
        chmod 600 "$INSTANCE_DIR/.env"
    fi

    # --- Clone code into instance dir ---
    if [[ -d "$CODE_DIR/.git" ]]; then
        log "Code already cloned — pulling latest on branch $BRANCH..."
        git -C "$CODE_DIR" fetch origin
        git -C "$CODE_DIR" checkout "$BRANCH"
        git -C "$CODE_DIR" pull --ff-only
    else
        log "Cloning codebase to $CODE_DIR (branch: $BRANCH)..."
        git clone --branch "$BRANCH" "$REPO_URL" "$CODE_DIR"
    fi
    chown -R "$INSTANCE_USER:$INSTANCE_USER" "$CODE_DIR"

    # --- Build frontend ---
    log "Building frontend for instance $INSTANCE..."
    sudo -u "$INSTANCE_USER" bash -c "
        cd '$CODE_DIR/frontend'
        npm run build
    "

    # --- Run Django commands as instance user ---
    log "Running Django setup (collectstatic + migrate)..."
    sudo -u "$INSTANCE_USER" bash -c "
        source '$SHARED_VENV/bin/activate'
        set -a
        source '$INSTANCE_DIR/.env'
        set +a
        cd '$CODE_DIR'
        python manage.py collectstatic --no-input
        python manage.py migrate --no-input
    "

    # --- Optionally seed data ---
    if [[ "$SEED" == "true" ]]; then
        log "Loading demo fixtures..."
        sudo -u "$INSTANCE_USER" bash -c "
            source '$SHARED_VENV/bin/activate'
            set -a
            source '$INSTANCE_DIR/.env'
            set +a
            cd '$CODE_DIR'
            python manage.py loaddata demo_fixtures
        "
    fi

    # --- Install systemd service ---
    log "Installing systemd service gunicorn-$INSTANCE..."
    sed \
        -e "s/__INSTANCE__/$INSTANCE/g" \
        "$TEMPLATE_DIR/gunicorn-instance.service.template" \
        > "/etc/systemd/system/gunicorn-$INSTANCE.service"
    systemctl daemon-reload
    systemctl enable "gunicorn-$INSTANCE"
    systemctl restart "gunicorn-$INSTANCE"

    # --- Install Nginx server block ---
    log "Installing Nginx config for $INSTANCE.$DOMAIN..."
    sed \
        -e "s/__INSTANCE__/$INSTANCE/g" \
        -e "s/__DOMAIN__/$DOMAIN/g" \
        "$TEMPLATE_DIR/nginx-instance.conf.template" \
        > "/etc/nginx/sites-available/docketworks-$INSTANCE"
    ln -sf "/etc/nginx/sites-available/docketworks-$INSTANCE" "/etc/nginx/sites-enabled/"
    nginx -t
    systemctl reload nginx

    # --- Summary ---
    log "=========================================="
    log "Instance '$INSTANCE' created successfully"
    log "  URL:        https://$INSTANCE.$DOMAIN"
    log "  Directory:  $INSTANCE_DIR"
    log "  User:       $INSTANCE_USER"
    log "  Code:       $CODE_DIR (branch: $BRANCH)"
    log "  Database:   $DB_NAME"
    log "  Service:    gunicorn-$INSTANCE"
    log "=========================================="

    echo ""
    echo "  DB password saved in: $INSTANCE_DIR/.env"
    echo ""
    echo "  IMPORTANT: Update the following in $INSTANCE_DIR/.env:"
    echo "    - XERO_CLIENT_ID / XERO_CLIENT_SECRET"
    echo "    - EMAIL_USER / EMAIL_PASSWORD (if email needed)"
    echo ""
    echo "  Then restart: sudo systemctl restart gunicorn-$INSTANCE"
}

# ============================================================
# destroy
# ============================================================
do_destroy() {
    if [[ $# -ne 1 ]]; then
        echo "Usage: $0 destroy <instance-name>"
        exit 1
    fi

    local INSTANCE="$1"
    local INSTANCE_DIR="$INSTANCES_DIR/$INSTANCE"
    local INSTANCE_USER="dw-$INSTANCE"
    local DB_NAME="docketworks_${INSTANCE//-/_}"
    local DB_USER="docketworks_${INSTANCE//-/_}"

    echo "=== Destroying instance: $INSTANCE ==="
    echo ""
    echo "  This will permanently delete:"
    echo "    - Directory: $INSTANCE_DIR"
    echo "    - Database:  $DB_NAME"
    echo "    - User:      $INSTANCE_USER"
    echo "    - Service:   gunicorn-$INSTANCE"
    echo "    - Nginx:     docketworks-$INSTANCE"
    echo ""
    read -p "Are you sure? (yes/no): " CONFIRM
    if [[ "$CONFIRM" != "yes" ]]; then
        echo "Aborted."
        exit 0
    fi

    # --- Stop and remove systemd service ---
    if systemctl is-active --quiet "gunicorn-$INSTANCE" 2>/dev/null; then
        echo "=== Stopping Gunicorn service ==="
        systemctl stop "gunicorn-$INSTANCE"
    fi
    if [[ -f "/etc/systemd/system/gunicorn-$INSTANCE.service" ]]; then
        echo "=== Removing systemd service ==="
        systemctl disable "gunicorn-$INSTANCE" 2>/dev/null || true
        rm -f "/etc/systemd/system/gunicorn-$INSTANCE.service"
        systemctl daemon-reload
    fi

    # --- Remove Nginx config ---
    if [[ -f "/etc/nginx/sites-available/docketworks-$INSTANCE" ]]; then
        echo "=== Removing Nginx config ==="
        rm -f "/etc/nginx/sites-enabled/docketworks-$INSTANCE"
        rm -f "/etc/nginx/sites-available/docketworks-$INSTANCE"
        nginx -t && systemctl reload nginx
    fi

    # --- Drop database and user ---
    echo "=== Dropping database and user ==="
    mysql -u root <<EOSQL || true
DROP DATABASE IF EXISTS \`$DB_NAME\`;
DROP USER IF EXISTS '$DB_USER'@'localhost';
FLUSH PRIVILEGES;
EOSQL

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

    printf "%-15s %-12s %-20s %-40s\n" "INSTANCE" "STATUS" "BRANCH" "URL"
    printf "%-15s %-12s %-20s %-40s\n" "--------" "------" "------" "---"

    for name in "${INSTANCES[@]}"; do
        local status branch
        if systemctl is-active --quiet "gunicorn-$name" 2>/dev/null; then
            status="running"
        elif systemctl is-enabled --quiet "gunicorn-$name" 2>/dev/null; then
            status="stopped"
        else
            status="no service"
        fi

        local code_dir="$INSTANCES_DIR/$name/code"
        if [[ -d "$code_dir/.git" ]]; then
            branch="$(git -C "$code_dir" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")"
        else
            branch="no code"
        fi

        printf "%-15s %-12s %-20s %-40s\n" "$name" "$status" "$branch" "https://$name.$DOMAIN"
    done
}

# ============================================================
# main
# ============================================================
if [[ $# -lt 1 ]]; then
    echo "Usage: $0 {create|destroy|list} [args...]"
    exit 1
fi

COMMAND="$1"; shift

if [[ "$COMMAND" != "list" && $EUID -ne 0 ]]; then
    echo "ERROR: This script must be run as root (use sudo)."
    exit 1
fi

case "$COMMAND" in
    create)  do_create "$@" ;;
    destroy) do_destroy "$@" ;;
    list)    do_list ;;
    *)       echo "Unknown command: $COMMAND"; echo "Usage: $0 {create|destroy|list} [args...]"; exit 1 ;;
esac
