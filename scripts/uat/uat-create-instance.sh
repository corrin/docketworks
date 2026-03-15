#!/bin/bash
set -euo pipefail

# Creates a new UAT/demo instance of docketworks.
# Usage: uat-create-instance.sh <name> [--seed]
#
# Requires: run as root or with sudo
# Assumes base server setup is complete (see docs/uat_setup.md)

DOMAIN="docketworks.site"
BASE_DIR="/opt/docketworks"
REPO_URL="git@github.com:corrin/docketworks.git"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TEMPLATE_DIR="$SCRIPT_DIR/templates"
SETUP_LOG="/var/log/docketworks-setup.log"

# --- Logging helper ---
log() {
    local msg="[$(date '+%Y-%m-%d %H:%M:%S')] $*"
    echo "$msg" | tee -a "$SETUP_LOG"
}

usage() {
    echo "Usage: $0 <instance-name> [--seed]"
    echo ""
    echo "  <instance-name>  Short name (e.g., 'msm', 'acme'). Alphanumeric and hyphens only."
    echo "  --seed           Load demo fixtures after migration."
    exit 1
}

if [[ $# -lt 1 ]]; then
    usage
fi

INSTANCE="$1"
SEED=false

if [[ ! "$INSTANCE" =~ ^[a-z0-9][a-z0-9-]*$ ]]; then
    echo "ERROR: Instance name must be lowercase alphanumeric (hyphens allowed, cannot start with hyphen)."
    exit 1
fi

shift
while [[ $# -gt 0 ]]; do
    case "$1" in
        --seed) SEED=true; shift ;;
        *) echo "Unknown option: $1"; usage ;;
    esac
done

INSTANCE_DIR="$BASE_DIR/$INSTANCE"
DB_NAME="docketworks_${INSTANCE//-/_}"
DB_USER="docketworks_${INSTANCE//-/_}"

if [[ -d "$INSTANCE_DIR" ]]; then
    echo "ERROR: Instance directory $INSTANCE_DIR already exists."
    exit 1
fi

log "=========================================="
log "Creating docketworks instance: $INSTANCE"
log "  Directory: $INSTANCE_DIR"
log "  Database:  $DB_NAME"
log "  URL:       https://$INSTANCE.$DOMAIN"
log "=========================================="

# --- Generate credentials ---
DB_PASSWORD="$(openssl rand -base64 24 | tr -d '/+=' | head -c 32)"
SECRET_KEY="$(python3 -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())')"

# --- Clone repository ---
log "Cloning repository to $INSTANCE_DIR..."
sudo -u docketworks git clone "$REPO_URL" "$INSTANCE_DIR"

# --- Create MySQL database and user ---
log "Creating database $DB_NAME and user $DB_USER..."
mysql -u root <<EOSQL
CREATE DATABASE \`$DB_NAME\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS '$DB_USER'@'localhost' IDENTIFIED BY '$DB_PASSWORD';
GRANT ALL PRIVILEGES ON \`$DB_NAME\`.* TO '$DB_USER'@'localhost';
FLUSH PRIVILEGES;
EOSQL

# --- Generate .env from template ---
log "Generating .env from template..."
sed \
    -e "s/__INSTANCE__/$INSTANCE/g" \
    -e "s/__DOMAIN__/$DOMAIN/g" \
    -e "s/__DB_PASSWORD__/$DB_PASSWORD/g" \
    -e "s/__SECRET_KEY__/$SECRET_KEY/g" \
    -e "s/__XERO_CLIENT_ID__/REPLACE_ME/g" \
    -e "s/__XERO_CLIENT_SECRET__/REPLACE_ME/g" \
    -e "s/__EMAIL_USER__/REPLACE_ME/g" \
    -e "s/__EMAIL_PASSWORD__/REPLACE_ME/g" \
    "$TEMPLATE_DIR/env-instance.template" > "$INSTANCE_DIR/.env"
chown docketworks:docketworks "$INSTANCE_DIR/.env"
chmod 600 "$INSTANCE_DIR/.env"

# --- Python virtual environment + dependencies ---
log "Setting up Python environment..."
sudo -u docketworks bash -c "
    cd '$INSTANCE_DIR'
    python3.12 -m venv .venv
    source .venv/bin/activate
    pip install --upgrade pip
    pip install poetry
    poetry install --no-interaction
"

# --- Run migrations ---
log "Running migrations and collectstatic..."
sudo -u docketworks bash -c "
    cd '$INSTANCE_DIR'
    source .venv/bin/activate
    python manage.py migrate --no-input
    python manage.py collectstatic --no-input
"

# --- Optionally seed data ---
if $SEED; then
    log "Loading demo fixtures..."
    sudo -u docketworks bash -c "
        cd '$INSTANCE_DIR'
        source .venv/bin/activate
        python manage.py loaddata demo_fixtures
    "
fi

# --- Build frontend ---
log "Building frontend..."
sudo -u docketworks bash -c "
    cd '$INSTANCE_DIR/frontend'
    npm install
    VITE_API_BASE_URL='https://$INSTANCE.$DOMAIN' npm run build
"

# --- Install systemd service ---
log "Installing systemd service gunicorn-$INSTANCE..."
sed \
    -e "s/__INSTANCE__/$INSTANCE/g" \
    "$TEMPLATE_DIR/gunicorn-instance.service.template" \
    > "/etc/systemd/system/gunicorn-$INSTANCE.service"
systemctl daemon-reload
systemctl enable "gunicorn-$INSTANCE"
systemctl start "gunicorn-$INSTANCE"

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
