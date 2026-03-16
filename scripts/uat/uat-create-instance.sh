#!/bin/bash
set -euo pipefail

# Creates a new UAT/demo instance of docketworks.
# Root-only operations here; all app-level work delegated to uat-instance-worker.sh.
# Usage: uat-create-instance.sh <name> [--seed] [--branch <branch>]
#
# Requires: run as root or with sudo
# Assumes base server setup is complete (see uat-base-setup.sh)

DOMAIN="docketworks.site"
BASE_DIR="/opt/docketworks"
INSTANCES_DIR="$BASE_DIR/instances"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TEMPLATE_DIR="$SCRIPT_DIR/templates"
SETUP_LOG="/var/log/docketworks-setup.log"

# --- Logging helper ---
log() {
    local msg="[$(date '+%Y-%m-%d %H:%M:%S')] $*"
    echo "$msg" | tee -a "$SETUP_LOG"
}

usage() {
    echo "Usage: $0 <instance-name> [--seed] [--branch <branch>]"
    echo ""
    echo "  <instance-name>  Short name (e.g., 'msm', 'acme'). Alphanumeric and hyphens only."
    echo "  --seed           Load demo fixtures after migration."
    echo "  --branch <name>  Git branch to check out (default: main)."
    exit 1
}

if [[ $# -lt 1 ]]; then
    usage
fi

INSTANCE="$1"
SEED=false
BRANCH="main"

if [[ ! "$INSTANCE" =~ ^[a-z0-9][a-z0-9-]*$ ]]; then
    echo "ERROR: Instance name must be lowercase alphanumeric (hyphens allowed, cannot start with hyphen)."
    exit 1
fi

shift
while [[ $# -gt 0 ]]; do
    case "$1" in
        --seed) SEED=true; shift ;;
        --branch) BRANCH="$2"; shift 2 ;;
        *) echo "Unknown option: $1"; usage ;;
    esac
done

INSTANCE_DIR="$INSTANCES_DIR/$INSTANCE"
DB_NAME="docketworks_${INSTANCE//-/_}"
DB_USER="docketworks_${INSTANCE//-/_}"

if [[ -d "$INSTANCE_DIR" ]]; then
    log "Instance directory $INSTANCE_DIR already exists — will update in place."
fi

log "=========================================="
log "Creating docketworks instance: $INSTANCE"
log "  Directory: $INSTANCE_DIR"
log "  Code:      $INSTANCE_DIR/code (branch: $BRANCH)"
log "  Database:  $DB_NAME"
log "  URL:       https://$INSTANCE.$DOMAIN"
log "=========================================="

# --- Create instance directory structure (root) ---
log "Creating instance directory structure..."
mkdir -p "$INSTANCE_DIR"/{logs,mediafiles,staticfiles}
chown -R docketworks:docketworks "$INSTANCE_DIR"

# --- Generate credentials ---
DB_PASSWORD="$(openssl rand -base64 24 | tr -d '/+=' | head -c 32)"
SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(50))')"

# --- Create MySQL database and user (root) ---
log "Creating database $DB_NAME and user $DB_USER (if not exists)..."
mysql -u root <<EOSQL
CREATE DATABASE IF NOT EXISTS \`$DB_NAME\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS '$DB_USER'@'localhost' IDENTIFIED BY '$DB_PASSWORD';
GRANT ALL PRIVILEGES ON \`$DB_NAME\`.* TO '$DB_USER'@'localhost';
FLUSH PRIVILEGES;
EOSQL

# --- Generate .env from template (root, skip if already exists) ---
if [[ -f "$INSTANCE_DIR/.env" ]]; then
    log ".env already exists — skipping (credentials preserved)."
else
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
    chown docketworks:docketworks "$INSTANCE_DIR/.env"
    chmod 600 "$INSTANCE_DIR/.env"
fi

# --- Run worker script as docketworks user (all app-level work) ---
log "Running worker script as docketworks user..."
sudo -u docketworks bash "$SCRIPT_DIR/uat-instance-worker.sh" "$INSTANCE" "$BRANCH" "$SEED"

# --- Install systemd service (root) ---
log "Installing systemd service gunicorn-$INSTANCE..."
sed \
    -e "s/__INSTANCE__/$INSTANCE/g" \
    "$TEMPLATE_DIR/gunicorn-instance.service.template" \
    > "/etc/systemd/system/gunicorn-$INSTANCE.service"
systemctl daemon-reload
systemctl enable "gunicorn-$INSTANCE"
systemctl restart "gunicorn-$INSTANCE"

# --- Install Nginx server block (root) ---
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
log "  Code:       $INSTANCE_DIR/code (branch: $BRANCH)"
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
