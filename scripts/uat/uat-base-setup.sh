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

# --- Nginx ---

if dpkg -l | grep -q "ii  nginx "; then
    log "Nginx already installed, skipping."
else
    log "Installing Nginx..."
    apt install -y nginx
fi
log_version "nginx" "$(nginx -v 2>&1)"
systemctl enable --now nginx

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

# --- SSH directory for docketworks user ---

if [[ ! -d /opt/docketworks/.ssh ]]; then
    log "Creating .ssh directory for docketworks user..."
    mkdir -p /opt/docketworks/.ssh
    chown docketworks:docketworks /opt/docketworks/.ssh
    chmod 700 /opt/docketworks/.ssh
fi

# --- Poetry for docketworks user ---

if sudo -u docketworks bash -c 'command -v poetry' &>/dev/null; then
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
log "  Wrote /etc/nginx/sites-available/default"
# Don't test/reload yet — SSL cert may not exist on first run

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

# --- Summary ---

log "=========================================="
log "Base server setup complete"
log "=========================================="
log ""
log "Next steps:"
log "  1. Set up SSH deploy key:"
log "     sudo -u docketworks ssh-keygen -t ed25519 -C 'docketworks-demo' -f /opt/docketworks/.ssh/id_ed25519 -N ''"
log "     cat /opt/docketworks/.ssh/id_ed25519.pub"
log "     (Add as deploy key in GitHub repo settings)"
log ""
log "  2. Save Dreamhost API key:"
log "     echo 'YOUR_API_KEY' | sudo tee /etc/letsencrypt/dreamhost-api-key.txt"
log "     sudo chmod 600 /etc/letsencrypt/dreamhost-api-key.txt"
log ""
log "  3. Obtain wildcard SSL certificate:"
log "     sudo certbot certonly --manual --preferred-challenges dns \\"
log "         --manual-auth-hook /opt/docketworks/certbot-hooks/auth.sh \\"
log "         --manual-cleanup-hook /opt/docketworks/certbot-hooks/cleanup.sh \\"
log "         -d '*.docketworks.site' -d 'docketworks.site'"
log ""
log "  4. Then test and reload Nginx:"
log "     sudo nginx -t && sudo systemctl reload nginx"
log ""
log "  5. Create instances:"
log "     sudo scripts/uat/uat-create-instance.sh msm"
log ""
log "Install log:      $SETUP_LOG"
log "Server manifest:  $MANIFEST"
