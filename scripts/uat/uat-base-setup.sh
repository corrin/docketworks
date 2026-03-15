#!/bin/bash
set -euo pipefail

# Base server setup for UAT/demo environment.
# Runs once on a fresh Ubuntu 24.04 ARM server as the 'ubuntu' user.
# Idempotent — safe to re-run.
#
# Usage: sudo ./uat-base-setup.sh

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

mkdir -p "$(dirname "$SETUP_LOG")"
touch "$SETUP_LOG"

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

log "Installing build dependencies (build-essential, libmariadb-dev, pkg-config)..."
apt install -y build-essential libmariadb-dev pkg-config
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

# --- MariaDB ---

if dpkg -l | grep -q mariadb-server; then
    log "MariaDB server already installed, skipping."
else
    log "Installing MariaDB server..."
    apt install -y mariadb-server
fi
log_version "mariadb" "$(mariadb --version)"
log "Starting and enabling MariaDB..."
systemctl enable --now mariadb

# Secure MariaDB (non-interactive equivalent of mariadb-secure-installation)
log "Securing MariaDB installation..."
mariadb -u root <<'EOSQL'
-- Remove anonymous users
DELETE FROM mysql.user WHERE User='';
-- Disallow root remote login
DELETE FROM mysql.user WHERE User='root' AND Host NOT IN ('localhost', '127.0.0.1', '::1');
-- Remove test database
DROP DATABASE IF EXISTS test;
DELETE FROM mysql.db WHERE Db='test' OR Db='test\\_%';
-- Reload privileges
FLUSH PRIVILEGES;
EOSQL
log "  MariaDB secured (anonymous users removed, remote root disabled, test DB dropped)."

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
systemctl enable --now nginx
# SSL config is written later after certbot obtains certs

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
mkdir -p /opt/docketworks/.ssh /opt/docketworks/.local/share /opt/docketworks/.local/bin
chown -R docketworks:docketworks /opt/docketworks
chmod 700 /opt/docketworks/.ssh

# --- SSH deploy key for docketworks user ---

if [[ -f /opt/docketworks/.ssh/id_ed25519 ]]; then
    log "SSH deploy key already exists, skipping."
else
    log "Generating SSH deploy key for docketworks user..."
    sudo -u docketworks ssh-keygen -t ed25519 -C "docketworks-demo" -f /opt/docketworks/.ssh/id_ed25519 -N ""
    log "  Deploy key generated."
    echo ""
    echo "============================================================"
    echo "  ACTION REQUIRED: Add this deploy key to GitHub repo settings"
    echo "  (Settings > Deploy keys > Add deploy key)"
    echo ""
    cat /opt/docketworks/.ssh/id_ed25519.pub
    echo ""
    echo "  Press Enter once you've added it to continue..."
    echo "============================================================"
    read -r
fi

# --- Dreamhost API key for SSL cert renewal ---

if [[ -f /etc/letsencrypt/dreamhost-api-key.txt ]]; then
    log "Dreamhost API key already configured, skipping."
else
    echo ""
    echo "============================================================"
    echo "  ACTION REQUIRED: Dreamhost API key needed for SSL certs"
    echo "  Get one from: panel.dreamhost.com → Home > API"
    echo "  Grant it dns-* permissions."
    echo ""
    read -rp "  Paste your Dreamhost API key (or leave blank to skip): " API_KEY
    if [[ -n "$API_KEY" ]]; then
        mkdir -p /etc/letsencrypt
        echo "$API_KEY" > /etc/letsencrypt/dreamhost-api-key.txt
        chmod 600 /etc/letsencrypt/dreamhost-api-key.txt
        log "  Dreamhost API key saved to /etc/letsencrypt/dreamhost-api-key.txt"
    else
        log "  WARNING: Dreamhost API key skipped. Wildcard SSL cert will need manual setup."
    fi
    echo "============================================================"
fi

# --- Poetry for docketworks user ---

if sudo -u docketworks bash -c 'export PATH="/opt/docketworks/.local/bin:$PATH" && command -v poetry' &>/dev/null; then
    log "Poetry already installed for docketworks user, skipping."
else
    log "Installing Poetry for docketworks user..."
    sudo -u docketworks bash -c 'curl -sSL https://install.python-poetry.org | python3.12 -'
fi
POETRY_VERSION="$(sudo -u docketworks bash -c 'export PATH="/opt/docketworks/.local/bin:$PATH" && poetry --version' 2>&1)"
log_version "poetry (docketworks user)" "$POETRY_VERSION"

# --- Claude Code CLI ---

if command -v claude &>/dev/null; then
    log "Claude Code already installed, skipping."
else
    log "Installing Claude Code CLI..."
    npm install -g @anthropic-ai/claude-code
fi
log_version "claude" "$(claude --version 2>&1 || echo 'not available')"

# --- Wildcard SSL certificate ---

if [[ -f /etc/letsencrypt/live/docketworks.site/fullchain.pem ]]; then
    log "Wildcard SSL certificate already exists, skipping."
elif [[ -f /etc/letsencrypt/dreamhost-api-key.txt ]]; then
    log "Obtaining wildcard SSL certificate via Dreamhost DNS..."
    log "  This will take ~2-4 minutes (DNS propagation wait)."
    certbot certonly --manual --preferred-challenges dns \
        --manual-auth-hook /opt/docketworks/certbot-hooks/auth.sh \
        --manual-cleanup-hook /opt/docketworks/certbot-hooks/cleanup.sh \
        -d "*.docketworks.site" -d "docketworks.site" \
        --non-interactive --agree-tos --email admin@docketworks.site
    log "  Wildcard SSL certificate obtained."
else
    log "WARNING: No Dreamhost API key — skipping SSL cert. Nginx will run HTTP-only."
fi

# --- Base Nginx config (reject unknown hosts) ---

log "Installing base Nginx config (reject unknown hosts)..."
if [[ -f /etc/letsencrypt/live/docketworks.site/fullchain.pem ]]; then
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
    log "  Wrote default config with SSL."
else
    cat > /etc/nginx/sites-available/default <<'EOF'
server {
    listen 80 default_server;
    server_name _;
    return 444;
}
EOF
    log "  Wrote default config without SSL (no certs yet)."
fi
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
MariaDB:    $(mariadb --version)
Nginx:      $(nginx -v 2>&1)
Certbot:    $(certbot --version 2>&1)
Git:        $(git --version)
Poetry:     $POETRY_VERSION
Claude:     $(claude --version 2>&1 || echo 'not available')

## System User

docketworks (home: /opt/docketworks, groups: $(id -nG docketworks))

## Firewall

Port 80:  open (iptables)
Port 443: open (iptables)

## Setup Log

Full install log: $SETUP_LOG
MANIFEST

log "Server manifest written to $MANIFEST"

# --- Clone shared codebase ---

REPO_URL="git@github.com:corrin/docketworks.git"
SHARED_DIR="/opt/docketworks/shared"

if [[ -d "$SHARED_DIR/.git" ]]; then
    log "Shared codebase already cloned — pulling latest..."
    sudo -u docketworks git -C "$SHARED_DIR" pull --ff-only
else
    log "Cloning shared codebase to $SHARED_DIR..."
    sudo -u docketworks git clone "$REPO_URL" "$SHARED_DIR"
fi

log "Setting up shared Python environment..."
sudo -u docketworks bash -c "
    cd '$SHARED_DIR'
    if [[ ! -d .venv ]]; then
        python3.12 -m venv .venv
    fi
    source .venv/bin/activate
    pip install --upgrade pip
    export PATH='/opt/docketworks/.local/bin:\$PATH'
    poetry install --no-interaction
"

log "Building shared frontend..."
sudo -u docketworks bash -c "
    cd '$SHARED_DIR/frontend'
    npm install
    npm run build
"

log "Collecting shared static files..."
sudo -u docketworks bash -c "
    cd '$SHARED_DIR'
    source .venv/bin/activate
    python manage.py collectstatic --no-input
"

mkdir -p /opt/docketworks/instances
chown docketworks:docketworks /opt/docketworks/instances

# --- Summary ---

log "=========================================="
log "Base server setup complete"
log "=========================================="
log ""
log "Next step — create an instance:"
log "  sudo scripts/uat/uat-create-instance.sh msm"
log ""
log "Install log:      $SETUP_LOG"
log "Server manifest:  $MANIFEST"
