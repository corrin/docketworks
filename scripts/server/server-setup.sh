#!/bin/bash
set -euo pipefail

# Base server setup for docketworks.
# Runs once on a fresh Ubuntu 24.04 ARM server as the 'ubuntu' user.
# Idempotent — safe to re-run.
#
# First run:  sudo ./server-setup.sh <dreamhost-api-key> <google-maps-api-key>
# Re-run:     sudo ./server-setup.sh   (reads keys from files saved on first run)

SETUP_LOG="/var/log/docketworks-setup.log"
MANIFEST="/opt/docketworks/server-manifest.txt"

# --- Logging helpers ---

log() {
    local msg="[$(date '+%Y-%m-%d %H:%M:%S')] $*"
    echo "$msg" | tee -a "$SETUP_LOG"
}

log_version() {
    local name="$1"
    local version="$2"
    log "  Installed: $name $version"
}

# --- Pre-flight checks ---

if [[ $EUID -ne 0 ]]; then
    echo "ERROR: This script must be run as root (use sudo)."
    exit 1
fi

DREAMHOST_KEY_FILE="/etc/letsencrypt/dreamhost-api-key.txt"
SHARED_ENV_FILE="/opt/docketworks/shared.env"

if [[ $# -eq 2 ]]; then
    DREAMHOST_API_KEY="$1"
    GOOGLE_MAPS_API_KEY="$2"
elif [[ $# -eq 0 ]]; then
    # Re-run: read keys from files saved on first run
    if [[ ! -f "$DREAMHOST_KEY_FILE" ]]; then
        echo "ERROR: No Dreamhost API key found at $DREAMHOST_KEY_FILE"
        echo "First run requires: $0 <dreamhost-api-key> <google-maps-api-key>"
        exit 1
    fi
    if [[ ! -f "$SHARED_ENV_FILE" ]]; then
        echo "ERROR: No Google Maps API key found at $SHARED_ENV_FILE"
        echo "First run requires: $0 <dreamhost-api-key> <google-maps-api-key>"
        exit 1
    fi
    DREAMHOST_API_KEY="$(cat "$DREAMHOST_KEY_FILE")"
    GOOGLE_MAPS_API_KEY="$(grep GOOGLE_MAPS_API_KEY "$SHARED_ENV_FILE" | cut -d"'" -f2)"
else
    echo "Usage: $0 [<dreamhost-api-key> <google-maps-api-key>]"
    echo ""
    echo "  First run:  $0 <dreamhost-api-key> <google-maps-api-key>"
    echo "  Re-run:     $0   (reads keys from files saved on first run)"
    echo ""
    echo "  dreamhost-api-key:   panel.dreamhost.com → Home > API (grant dns-* permissions)"
    echo "  google-maps-api-key: GCP console → APIs & Services → Credentials"
    exit 1
fi

mkdir -p "$(dirname "$SETUP_LOG")"
touch "$SETUP_LOG"
chown docketworks:docketworks "$SETUP_LOG" 2>/dev/null || true
chmod 664 "$SETUP_LOG"

log "=========================================="
log "Base server setup starting"
log "=========================================="
log "Host: $(hostname)"
log "OS: $(lsb_release -ds 2>/dev/null || cat /etc/os-release | grep PRETTY_NAME | cut -d= -f2)"
log "Arch: $(uname -m)"

# --- System update ---

log "Updating system packages..."
apt update && apt upgrade -y
log "System packages updated."

# --- etckeeper (track /etc changes in git — install first) ---

if dpkg -l | grep -q "ii  etckeeper "; then
    log "etckeeper already installed, skipping."
else
    log "Installing etckeeper — tracks all /etc changes in git..."
    apt install -y etckeeper
    if [[ -d /etc/.git ]]; then
        log "  etckeeper initialized. /etc is now tracked in git."
    fi
fi
log_version "etckeeper" "$(dpkg -s etckeeper | grep Version | awk '{print $2}')"

# --- Build dependencies ---

log "Installing build dependencies (build-essential, libpq-dev, pkg-config, pandoc, unzip)..."
apt install -y build-essential libpq-dev pkg-config pandoc unzip
log_version "build-essential" "$(dpkg -s build-essential | grep Version | awk '{print $2}')"
log_version "pkg-config" "$(pkg-config --version)"

# --- Python 3.12 ---

log "Ensuring Python 3.12 and dev packages..."
apt install -y python3.12 python3.12-venv python3.12-dev
log_version "python3.12" "$(python3.12 --version 2>&1)"

# --- Node.js 22 (NodeSource) ---

if command -v node &>/dev/null && node --version | grep -q '^v22'; then
    log "Node.js 22 already installed, skipping."
else
    log "Installing Node.js 22 via NodeSource..."
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
    apt install -y nodejs
fi
log_version "node" "$(node --version)"
log_version "npm" "$(npm --version)"

# --- PostgreSQL ---

if dpkg -l | grep -q "ii  postgresql "; then
    log "PostgreSQL already installed, skipping."
else
    log "Installing PostgreSQL..."
    apt install -y postgresql postgresql-contrib
fi
log_version "postgresql" "$(psql --version)"
log "Starting and enabling PostgreSQL..."
systemctl enable --now postgresql

# Allow password auth over sockets for app users (keep peer for postgres).
# Without this, instance users can't connect via socket because their OS
# username (dw-msm-uat) doesn't match the DB role (dw_msm_uat).
PG_HBA="$(sudo -u postgres psql -t -c 'SHOW hba_file;' | tr -d ' ')"
if grep -q 'local.*all.*all.*peer' "$PG_HBA"; then
    log "Configuring pg_hba.conf for password auth over sockets..."
    sed -i 's/^local\s\+all\s\+all\s\+peer$/local   all             all                                     scram-sha-256/' "$PG_HBA"
    systemctl reload postgresql
fi

# --- Shared test runner user (used by all tenants for pytest) ---

log "Ensuring shared test DB user 'dw_test'..."
sudo -u postgres psql <<'EOSQL'
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'dw_test') THEN
        CREATE ROLE dw_test WITH LOGIN PASSWORD 'dw_test' CREATEDB;
    ELSE
        ALTER ROLE dw_test WITH PASSWORD 'dw_test' CREATEDB;
    END IF;
END
$$;
EOSQL
log "  Test DB user ready."

# --- Nginx ---

if dpkg -l | grep -q "ii  nginx "; then
    log "Nginx already installed, skipping."
else
    log "Installing Nginx..."
    apt install -y nginx
fi
log_version "nginx" "$(nginx -v 2>&1)"
# Write a safe default config before enabling — previous runs may have left
# a config referencing SSL certs that don't exist yet
cat > /etc/nginx/sites-available/default <<'EOF'
server {
    listen 80 default_server;
    server_name _;
    return 444;
}
EOF
# Don't start nginx yet — instance configs in sites-enabled/ may reference
# SSL certs that don't exist until after certbot runs below.
# Just enable the service so it starts on boot; the restart after SSL
# setup (below) will be the first start.
systemctl enable nginx

# --- Certbot ---

log "Installing Certbot..."
apt install -y certbot python3-certbot-nginx
log_version "certbot" "$(certbot --version 2>&1)"

# --- Certbot Dreamhost DNS hook scripts ---

HOOK_DIR="/opt/docketworks/certbot-hooks"
log "Installing Dreamhost DNS hook scripts to $HOOK_DIR..."
mkdir -p "$HOOK_DIR"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cp "$SCRIPT_DIR/certbot-dreamhost-auth.sh" "$HOOK_DIR/auth.sh"
cp "$SCRIPT_DIR/certbot-dreamhost-cleanup.sh" "$HOOK_DIR/cleanup.sh"
chmod 700 "$HOOK_DIR"/*.sh
log "  Hooks installed: $HOOK_DIR/auth.sh, $HOOK_DIR/cleanup.sh"

# --- Git ---

apt install -y git
log_version "git" "$(git --version)"

# --- netfilter-persistent (for iptables save) ---

apt install -y iptables-persistent netfilter-persistent
log_version "iptables" "$(iptables --version)"

# --- Firewall (Oracle Cloud iptables) ---

log "Configuring firewall — opening ports 80 and 443..."
# Check if rules already exist before adding
if ! iptables -C INPUT -m state --state NEW -p tcp --dport 80 -j ACCEPT 2>/dev/null; then
    iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
    log "  Added iptables rule for port 80."
else
    log "  Port 80 rule already exists, skipping."
fi

if ! iptables -C INPUT -m state --state NEW -p tcp --dport 443 -j ACCEPT 2>/dev/null; then
    iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
    log "  Added iptables rule for port 443."
else
    log "  Port 443 rule already exists, skipping."
fi

netfilter-persistent save
log "Firewall rules saved."

# --- Create docketworks system user ---

if id docketworks &>/dev/null; then
    log "User 'docketworks' already exists, skipping."
else
    log "Creating system user 'docketworks'..."
    useradd --system --shell /bin/bash --home-dir /opt/docketworks --create-home docketworks
    usermod -aG www-data docketworks
    log "  Created user 'docketworks' (home: /opt/docketworks, groups: www-data)."
fi

# --- Ensure home directory structure for docketworks user ---

log "Ensuring docketworks home directory structure..."
mkdir -p /opt/docketworks/.local/share /opt/docketworks/.local/bin
chown -R docketworks:docketworks /opt/docketworks

# --- Install Dreamhost API key for certbot hooks ---

if [[ -f /etc/letsencrypt/dreamhost-api-key.txt ]]; then
    log "Dreamhost API key already configured, skipping."
else
    mkdir -p /etc/letsencrypt
    echo "$DREAMHOST_API_KEY" > /etc/letsencrypt/dreamhost-api-key.txt
    chmod 600 /etc/letsencrypt/dreamhost-api-key.txt
    log "  Dreamhost API key saved to /etc/letsencrypt/dreamhost-api-key.txt"
fi

# --- Write shared.env (Google Maps key, sourced by instance .env files) ---

SHARED_ENV="/opt/docketworks/shared.env"
cat > "$SHARED_ENV" <<SHARED_EOF
GOOGLE_MAPS_API_KEY='$GOOGLE_MAPS_API_KEY'
SHARED_EOF
chown docketworks:docketworks "$SHARED_ENV"
chmod 600 "$SHARED_ENV"
log "  Shared config written to $SHARED_ENV"

# --- Poetry for docketworks user ---

if sudo -u docketworks bash -c 'export PATH="/opt/docketworks/.local/bin:$PATH" && command -v poetry' &>/dev/null; then
    log "Poetry already installed for docketworks user, skipping."
else
    log "Installing Poetry for docketworks user..."
    sudo -u docketworks bash -c 'curl -sSL https://install.python-poetry.org | python3.12 -'
fi
POETRY_VERSION="$(sudo -u docketworks bash -c 'export PATH="/opt/docketworks/.local/bin:$PATH" && poetry --version' 2>&1)"
log_version "poetry (docketworks user)" "$POETRY_VERSION"

# --- pnpm (via corepack) ---

if command -v pnpm &>/dev/null; then
    log "pnpm already installed, skipping."
else
    log "Installing pnpm via corepack..."
    corepack enable
    corepack prepare pnpm@latest --activate
fi
log_version "pnpm" "$(pnpm --version)"

# --- pm2 (Node process manager) ---

if command -v pm2 &>/dev/null; then
    log "pm2 already installed, skipping."
else
    log "Installing pm2..."
    npm install -g pm2
fi
log_version "pm2" "$(pm2 --version)"

# --- Claude Code CLI ---

if command -v claude &>/dev/null; then
    log "Claude Code already installed, skipping."
else
    log "Installing Claude Code CLI..."
    npm install -g @anthropic-ai/claude-code
fi
CLAUDE_VERSION="$(claude --version 2>&1 || echo 'not available')"
log_version "claude" "$CLAUDE_VERSION"

# --- Wildcard SSL certificate ---

if [[ -f /etc/letsencrypt/live/docketworks.site/fullchain.pem ]]; then
    log "Wildcard SSL certificate already exists, skipping."
else
    log "Obtaining wildcard SSL certificate via Dreamhost DNS..."
    log "  This will take ~2-4 minutes (DNS propagation wait)."
    certbot certonly --manual --preferred-challenges dns \
        --manual-auth-hook /opt/docketworks/certbot-hooks/auth.sh \
        --manual-cleanup-hook /opt/docketworks/certbot-hooks/cleanup.sh \
        -d "*.docketworks.site" -d "docketworks.site" \
        --non-interactive --agree-tos --email admin@docketworks.site
    log "  Wildcard SSL certificate obtained."
fi

# certbot certonly --manual doesn't create the standard SSL config files
# that the nginx plugin would. Instance nginx configs reference these,
# so we must ensure they exist.
if [[ ! -f /etc/letsencrypt/options-ssl-nginx.conf ]]; then
    log "Creating /etc/letsencrypt/options-ssl-nginx.conf..."
    curl -fsSL -o /etc/letsencrypt/options-ssl-nginx.conf \
        https://raw.githubusercontent.com/certbot/certbot/master/certbot-nginx/certbot_nginx/_internal/tls_configs/options-ssl-nginx.conf
fi
if [[ ! -f /etc/letsencrypt/ssl-dhparams.pem ]]; then
    log "Creating /etc/letsencrypt/ssl-dhparams.pem..."
    curl -fsSL -o /etc/letsencrypt/ssl-dhparams.pem \
        https://raw.githubusercontent.com/certbot/certbot/master/certbot/certbot/ssl-dhparams.pem
fi

# --- Base Nginx config (reject unknown hosts) ---

log "Installing base Nginx config (reject unknown hosts)..."
cat > /etc/nginx/sites-available/default <<'EOF'
server {
    listen 80 default_server;
    listen 443 ssl default_server;
    server_name _;

    ssl_certificate /etc/letsencrypt/live/docketworks.site/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/docketworks.site/privkey.pem;

    return 444;
}
EOF
nginx -t && systemctl restart nginx
log "  Nginx started."

# --- Write server manifest ---

log "Writing server manifest to $MANIFEST..."
mkdir -p "$(dirname "$MANIFEST")"
cat > "$MANIFEST" <<MANIFEST
# Docketworks Demo Server Manifest
# Generated: $(date '+%Y-%m-%d %H:%M:%S')
# Host: $(hostname)
# OS: $(lsb_release -ds 2>/dev/null || cat /etc/os-release | grep PRETTY_NAME | cut -d= -f2)
# Arch: $(uname -m)

## Installed Software

etckeeper:  $(dpkg -s etckeeper | grep Version | awk '{print $2}')
Python:     $(python3.12 --version 2>&1)
Node.js:    $(node --version)
npm:        $(npm --version)
PostgreSQL: $(psql --version)
Nginx:      $(nginx -v 2>&1)
Certbot:    $(certbot --version 2>&1)
Git:        $(git --version)
Poetry:     $POETRY_VERSION
pnpm:       $(pnpm --version)
pm2:        $(pm2 --version)
Claude:     $CLAUDE_VERSION

## System User

docketworks (home: /opt/docketworks, groups: $(id -nG docketworks))

## Firewall

Port 80:  open (iptables)
Port 443: open (iptables)

## Setup Log

Full install log: $SETUP_LOG
MANIFEST

log "Server manifest written to $MANIFEST"

# --- Create instances directory ---

mkdir -p /opt/docketworks/instances
chown docketworks:docketworks /opt/docketworks/instances

# --- Clone repository (HTTPS, no SSH key needed) ---

REMOTE_REPO_URL="https://github.com/corrin/docketworks.git"
LOCAL_REPO="/opt/docketworks/repo"

if [[ -d "$LOCAL_REPO/.git" ]]; then
    log "Repository already cloned at $LOCAL_REPO, pulling latest..."
    sudo -u docketworks git -C "$LOCAL_REPO" pull --ff-only
else
    log "Cloning repository to $LOCAL_REPO..."
    sudo -u docketworks git clone "$REMOTE_REPO_URL" "$LOCAL_REPO"
fi

# Mark the local repo as safe so instance users (dw-*) can clone from it.
# Uses --system so it applies to all users on the server.
# Idempotent: remove any existing entries before adding
git config --system --unset-all safe.directory "$LOCAL_REPO" 2>/dev/null || true
git config --system --add safe.directory "$LOCAL_REPO"
git config --system --unset-all safe.directory "${LOCAL_REPO}/.git" 2>/dev/null || true
git config --system --add safe.directory "${LOCAL_REPO}/.git"

# --- Create shared Python venv + install dependencies ---

SHARED_VENV="/opt/docketworks/.venv"

if [[ -d "$SHARED_VENV" ]]; then
    log "Shared venv already exists, updating dependencies..."
else
    log "Creating shared Python venv at $SHARED_VENV..."
    sudo -u docketworks python3.12 -m venv "$SHARED_VENV"
fi

sudo -u docketworks bash -c "
    export PATH='/opt/docketworks/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
    export POETRY_VIRTUALENVS_CREATE=false
    source '$SHARED_VENV/bin/activate'
    pip install --upgrade pip
    cd '$LOCAL_REPO'
    poetry install --no-interaction
"
log "  Shared Python dependencies installed."

# --- Install shared node_modules ---

log "Installing shared node_modules..."
sudo -u docketworks bash -c "
    cp '$LOCAL_REPO/frontend/package.json' '/opt/docketworks/package.json'
    cp '$LOCAL_REPO/frontend/package-lock.json' '/opt/docketworks/package-lock.json'
    cd /opt/docketworks
    npm install
"
log "  Shared node_modules installed."

# --- Summary ---

log "=========================================="
log "Base server setup complete"
log "=========================================="
log ""
log "Next step — create an instance:"
log "  sudo scripts/server/instance.sh create msm uat"
log ""
log "Install log:      $SETUP_LOG"
log "Server manifest:  $MANIFEST"
