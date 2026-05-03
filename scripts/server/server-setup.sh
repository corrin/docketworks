#!/bin/bash
set -euo pipefail

# Base server setup for docketworks.
# Runs once on a fresh Ubuntu 24.04 server as the 'ubuntu' user.
# Idempotent — safe to re-run.
#
# Every box needs a Dreamhost API key (all customer DNS is on Dreamhost,
# so DNS-01 challenges work uniformly). Every box also needs an explicit
# decision about which domains it serves certs for: one or more
# --cert-domain flags, or --no-cert-domain for a DR-posture box.
#
# First run (UAT):   sudo ./server-setup.sh --dreamhost-key <KEY> --google-maps-key <KEY> \
#                                           --cert-domain '*.docketworks.site'
# First run (prod):  sudo ./server-setup.sh --dreamhost-key <KEY> --google-maps-key <KEY> \
#                                           --cert-domain <customer-fqdn>
# First run (DR):    sudo ./server-setup.sh --dreamhost-key <KEY> --google-maps-key <KEY> \
#                                           --no-cert-domain
# Re-run:            sudo ./server-setup.sh   (reads everything from files saved on first run)

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

# sudo inherits the caller's cwd. If that's a directory the target user can't
# read (e.g. /home/ubuntu, mode 750 ubuntu:ubuntu), python/poetry/npm startup
# call getcwd(2), hit EACCES, and die before main() — which silently aborts
# the deploy before per-instance work runs. Anchor cwd to / so every sudo -u
# below inherits something universally readable.
cd /

DREAMHOST_KEY_FILE="/etc/letsencrypt/dreamhost-api-key.txt"
CERT_DOMAINS_FILE="/etc/letsencrypt/cert-domains.txt"
SHARED_ENV_FILE="/opt/docketworks/shared.env"

USAGE="Usage: $0 [--dreamhost-key <KEY>] [--google-maps-key <KEY>]
              [--cert-domain <FQDN> [--cert-domain <FQDN> ...] | --no-cert-domain]

  First install on UAT (wildcard cert):
    $0 --dreamhost-key <KEY> --google-maps-key <KEY> \\
       --cert-domain '*.docketworks.site'

  First install on UAT with extra client-branded URL:
    $0 --dreamhost-key <KEY> --google-maps-key <KEY> \\
       --cert-domain '*.docketworks.site' \\
       --cert-domain uat-office.morrissheetmetal.co.nz

  First install on prod:
    $0 --dreamhost-key <KEY> --google-maps-key <KEY> \\
       --cert-domain office.heuserlimited.com

  First install on DR (no certs obtained):
    $0 --dreamhost-key <KEY> --google-maps-key <KEY> --no-cert-domain

  Re-run on a configured server:
    $0   (reads everything from files saved on first run)

  --dreamhost-key:    panel.dreamhost.com → Home > API (grant dns-* permissions)
  --google-maps-key:  GCP console → APIs & Services → Credentials
  --cert-domain:      one cert per FQDN. Repeatable. Wildcards include the apex.
                      On a re-run with this flag, the supplied list REPLACES
                      the persisted list at $CERT_DOMAINS_FILE.
  --no-cert-domain:   explicit DR posture (no certs obtained). Mutually
                      exclusive with --cert-domain."

if ! parsed=$(getopt -o '' --long dreamhost-key:,google-maps-key:,cert-domain:,no-cert-domain -n "$(basename "$0")" -- "$@"); then
    echo "$USAGE" >&2
    exit 1
fi
eval set -- "$parsed"

DREAMHOST_API_KEY=""
GOOGLE_MAPS_API_KEY=""
DREAMHOST_KEY_GIVEN=false
GOOGLE_MAPS_KEY_GIVEN=false
CERT_DOMAINS=()
CERT_DOMAINS_GIVEN=false
NO_CERT_DOMAIN_GIVEN=false
while true; do
    case "$1" in
        --dreamhost-key)   DREAMHOST_API_KEY="$2";   DREAMHOST_KEY_GIVEN=true;   shift 2 ;;
        --google-maps-key) GOOGLE_MAPS_API_KEY="$2"; GOOGLE_MAPS_KEY_GIVEN=true; shift 2 ;;
        --cert-domain)     CERT_DOMAINS+=("$2");     CERT_DOMAINS_GIVEN=true;    shift 2 ;;
        --no-cert-domain)  NO_CERT_DOMAIN_GIVEN=true;                            shift ;;
        --)                shift; break ;;
    esac
done

if [[ $# -gt 0 ]]; then
    echo "ERROR: Unexpected positional arguments: $*" >&2
    echo "$USAGE" >&2
    exit 1
fi

if [[ "$CERT_DOMAINS_GIVEN" == true && "$NO_CERT_DOMAIN_GIVEN" == true ]]; then
    echo "ERROR: --cert-domain and --no-cert-domain are mutually exclusive." >&2
    exit 1
fi

# --- Resolve Dreamhost key (every box needs one) ---
if [[ "$DREAMHOST_KEY_GIVEN" == false ]]; then
    if [[ ! -f "$DREAMHOST_KEY_FILE" ]]; then
        echo "ERROR: --dreamhost-key not given and no saved key at $DREAMHOST_KEY_FILE" >&2
        echo "" >&2
        echo "$USAGE" >&2
        exit 1
    fi
    DREAMHOST_API_KEY="$(cat "$DREAMHOST_KEY_FILE")"
fi

# --- Resolve Google Maps key (unchanged) ---
if [[ "$GOOGLE_MAPS_KEY_GIVEN" == false ]]; then
    if [[ ! -f "$SHARED_ENV_FILE" ]]; then
        echo "ERROR: --google-maps-key not given and no saved value in $SHARED_ENV_FILE" >&2
        echo "$USAGE" >&2
        exit 1
    fi
    GOOGLE_MAPS_API_KEY="$(grep GOOGLE_MAPS_API_KEY "$SHARED_ENV_FILE" | cut -d"'" -f2)"
fi

# --- Resolve cert-domains list ---
# Migration auto-detect: an existing UAT box that predates this rework has
# the wildcard live-dir but no cert-domains.txt yet. The live-dir at
# /etc/letsencrypt/live/docketworks.site/ is unambiguous evidence — only a
# previous successful UAT bootstrap creates it — so writing the standard UAT
# entry is safe. Never fires on a prod or DR box because they don't have
# that path. Runs before the explicit-flag handling below so an operator
# override still wins.
if [[ ! -f "$CERT_DOMAINS_FILE" && -d /etc/letsencrypt/live/docketworks.site ]]; then
    mkdir -p "$(dirname "$CERT_DOMAINS_FILE")"
    cat > "$CERT_DOMAINS_FILE" <<'CERT_DOMAINS_EOF'
# Cert domains for this server. One FQDN per line.
# Wildcards (*.example.com) include the apex (example.com) automatically.
# Edit to add or remove individual domains.
*.docketworks.site
CERT_DOMAINS_EOF
fi

if [[ "$CERT_DOMAINS_GIVEN" == true ]]; then
    # Explicit --cert-domain replaces the persisted list.
    mkdir -p "$(dirname "$CERT_DOMAINS_FILE")"
    {
        echo "# Cert domains for this server. One FQDN per line."
        echo "# Wildcards (*.example.com) include the apex (example.com) automatically."
        echo "# Edit to add or remove individual domains."
        for d in "${CERT_DOMAINS[@]}"; do printf '%s\n' "$d"; done
    } > "$CERT_DOMAINS_FILE"
elif [[ "$NO_CERT_DOMAIN_GIVEN" == true ]]; then
    # Explicit DR posture: header-only file, no FQDNs.
    mkdir -p "$(dirname "$CERT_DOMAINS_FILE")"
    cat > "$CERT_DOMAINS_FILE" <<'CERT_DOMAINS_EOF'
# DR posture: no cert domains configured for this server.
CERT_DOMAINS_EOF
    CERT_DOMAINS=()
elif [[ -f "$CERT_DOMAINS_FILE" ]]; then
    # Re-run: read from disk, ignoring blanks and #-comments.
    CERT_DOMAINS=()
    while IFS= read -r line; do
        line="${line%%#*}"
        line="${line//[[:space:]]/}"
        [[ -z "$line" ]] && continue
        CERT_DOMAINS+=("$line")
    done < "$CERT_DOMAINS_FILE"
else
    echo "ERROR: --cert-domain or --no-cert-domain not given, and no saved list at $CERT_DOMAINS_FILE" >&2
    echo "" >&2
    echo "$USAGE" >&2
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

# --- System packages (all unconditional installs in one pass) ---

log "Installing system packages..."
DEBIAN_FRONTEND=noninteractive apt install -y \
    etckeeper \
    build-essential libpq-dev pkg-config pandoc unzip \
    python3.12 python3.12-venv python3.12-dev \
    git \
    iptables-persistent netfilter-persistent \
    quota \
    unattended-upgrades
log "System packages installed."
if [[ -d /etc/.git ]]; then
    log "  etckeeper initialized. /etc is now tracked in git."
fi
log_version "etckeeper" "$(dpkg -s etckeeper | grep Version | awk '{print $2}')"
log_version "build-essential" "$(dpkg -s build-essential | grep Version | awk '{print $2}')"
log_version "pkg-config" "$(pkg-config --version)"
log_version "python3.12" "$(python3.12 --version 2>&1)"
log_version "unattended-upgrades" "$(dpkg -s unattended-upgrades | grep '^Version:' | awk '{print $2}')"

# --- Unattended security upgrades ---
# Daily auto-install of security patches via the unattended-upgrades
# package. Two systemd timers do all the work, completely independent
# of deploys: apt-daily.timer (apt update + download) and
# apt-daily-upgrade.timer (install). Auto-reboot at 03:00 (server-local)
# if a kernel update needs it. WithUsers=true reboots even if an SSH
# session is open — better than indefinitely deferring a security
# update because someone forgot to log out.
#
# Allowed-Origins is left at the distro default (security pockets only).
# Don't auto-bump packages from the regular -updates pocket — those can
# include feature-level changes (postgres, nginx) we want to upgrade
# deliberately.

log "Configuring unattended-upgrades..."
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'AUTO_UPG_EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
AUTO_UPG_EOF

cat > /etc/apt/apt.conf.d/51docketworks-unattended-upgrades <<'UNATT_EOF'
// Docketworks override of /etc/apt/apt.conf.d/50unattended-upgrades.
// Lives at 51 so it lexically follows the distro default and wins for
// the keys it sets. Keys NOT set here keep the distro default
// (notably Allowed-Origins — security pockets only).

Unattended-Upgrade::Automatic-Reboot "true";
Unattended-Upgrade::Automatic-Reboot-Time "03:00";
Unattended-Upgrade::Automatic-Reboot-WithUsers "true";
UNATT_EOF
log "  Configured: security pockets, auto-reboot 03:00 server-local."

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
# Per-instance OS users share the same name as their DB role
# (dw_<client>_<env>), so peer auth works for them — but per-instance
# pytest roles (dw_<client>_<env>_test) have no matching Linux user and
# require password auth. Keep the setting uniform for all non-postgres roles.
PG_HBA="$(sudo -u postgres psql -t -c 'SHOW hba_file;' | tr -d ' ')"
if grep -q 'local.*all.*all.*peer' "$PG_HBA"; then
    log "Configuring pg_hba.conf for password auth over sockets..."
    sed -i 's/^local\s\+all\s\+all\s\+peer$/local   all             all                                     scram-sha-256/' "$PG_HBA"
    systemctl reload postgresql
fi

# Test DB roles and DBs are provisioned per-instance by instance.sh — no
# cluster-wide test role exists. See scripts/server/instance.sh do_create.

# --- Redis ---

# Used as the Celery broker (db 1) and the Django Channels layer (db 0).
if dpkg -l | grep -q "ii  redis-server "; then
    log "Redis already installed, skipping."
else
    log "Installing Redis..."
    apt install -y redis-server
fi
log_version "redis-server" "$(redis-server --version)"
log "Starting and enabling Redis..."
systemctl enable --now redis-server

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
# Every box has a Dreamhost key, so the hooks always get installed —
# even DR-posture boxes, so adding a cert later requires no extra setup.

HOOK_DIR="/opt/docketworks/certbot-hooks"
log "Installing Dreamhost DNS hook scripts to $HOOK_DIR..."
mkdir -p "$HOOK_DIR"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cp "$SCRIPT_DIR/certbot-dreamhost-auth.sh" "$HOOK_DIR/auth.sh"
cp "$SCRIPT_DIR/certbot-dreamhost-cleanup.sh" "$HOOK_DIR/cleanup.sh"
chmod 700 "$HOOK_DIR"/*.sh
log "  Hooks installed: $HOOK_DIR/auth.sh, $HOOK_DIR/cleanup.sh"

log_version "git" "$(git --version)"
log_version "iptables" "$(iptables --version)"

# --- Filesystem quotas (per-instance disk limits) ---

log "Enabling filesystem quotas..."
QUOTA_MOUNT="$(df --output=target /opt | tail -1)"
if ! quotaon -p "$QUOTA_MOUNT" &>/dev/null; then
    log "  Enabling quotas on $QUOTA_MOUNT..."
    quotacheck -cum "$QUOTA_MOUNT"
    quotaon "$QUOTA_MOUNT"
    log "  Filesystem quotas enabled on $QUOTA_MOUNT"
else
    log "  Filesystem quotas already enabled on $QUOTA_MOUNT"
fi
log_version "quota" "$(dpkg -s quota | grep Version | awk '{print $2}')"

# --- Logrotate config for instance logs ---

if [[ ! -f /etc/logrotate.d/docketworks ]]; then
    log "Installing logrotate config for instance logs..."
    cp "$SCRIPT_DIR/templates/logrotate-docketworks.conf" /etc/logrotate.d/docketworks
    log "  Logrotate config installed."
else
    log "Logrotate config already installed, skipping."
fi

# --- Firewall ---

log "Configuring firewall — opening ports 80 and 443..."
# Check if rules already exist before adding
if ! iptables -C INPUT -m state --state NEW -p tcp --dport 80 -j ACCEPT 2>/dev/null; then
    iptables -I INPUT 1 -m state --state NEW -p tcp --dport 80 -j ACCEPT
    log "  Added iptables rule for port 80."
else
    log "  Port 80 rule already exists, skipping."
fi

if ! iptables -C INPUT -m state --state NEW -p tcp --dport 443 -j ACCEPT 2>/dev/null; then
    iptables -I INPUT 1 -m state --state NEW -p tcp --dport 443 -j ACCEPT
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
# Chown docketworks-owned scaffolding only. NEVER recurse into /opt/docketworks
# blindly — /opt/docketworks/instances/<inst>/ is owned by <inst_user>:www-data
# (see instance.sh) and a recursive chown here would clobber every instance on
# every deploy.
chown docketworks:docketworks /opt/docketworks
# Instance users (dw_*) are created with no supplementary groups (instance.sh
# uses `useradd --system` without -G), so they need world-x on /opt/docketworks
# to traverse into their own /opt/docketworks/instances/<inst>/ home dir.
# `useradd --create-home` honours HOME_MODE from /etc/login.defs, which is 0750
# on Ubuntu 21.04+ — so without this chmod, every instance user is locked out
# of its own home and gunicorn/celery/dw-run all fail with EACCES.
chmod 755 /opt/docketworks
chown -R docketworks:docketworks /opt/docketworks/.local

# --- Install Dreamhost API key for certbot hooks ---

if [[ -f "$DREAMHOST_KEY_FILE" ]]; then
    log "Dreamhost API key already configured, skipping."
else
    mkdir -p /etc/letsencrypt
    echo "$DREAMHOST_API_KEY" > "$DREAMHOST_KEY_FILE"
    chmod 600 "$DREAMHOST_KEY_FILE"
    log "  Dreamhost API key saved to $DREAMHOST_KEY_FILE"
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

# --- GitHub CLI ---

if command -v gh &>/dev/null; then
    log "GitHub CLI already installed, skipping."
else
    log "Installing GitHub CLI..."
    curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
        | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
        > /etc/apt/sources.list.d/github-cli.list
    apt update
    apt install -y gh
fi
log_version "gh" "$(gh --version | head -1)"

# --- Claude Code CLI ---

if command -v claude &>/dev/null; then
    log "Claude Code already installed, skipping."
else
    log "Installing Claude Code CLI..."
    npm install -g @anthropic-ai/claude-code
fi
CLAUDE_VERSION="$(claude --version 2>&1 || echo 'not available')"
log_version "claude" "$CLAUDE_VERSION"

# --- SSL certificates ---
# Iterate over every entry in CERT_DOMAINS, obtaining via Dreamhost DNS-01.
# Empty list (DR posture) → loop runs zero times. Already-present certs
# are skipped.

if (( ${#CERT_DOMAINS[@]} == 0 )); then
    log "No cert domains configured (DR posture); skipping cert acquisition."
else
    for DOMAIN in "${CERT_DOMAINS[@]}"; do
        # Wildcards always cover the apex too. Live-dir is named after the apex.
        case "$DOMAIN" in
            \*.*) APEX="${DOMAIN#*.}"
                  CERTBOT_D=( -d "$DOMAIN" -d "$APEX" )
                  LIVE_DIR="/etc/letsencrypt/live/$APEX" ;;
            *)    CERTBOT_D=( -d "$DOMAIN" )
                  LIVE_DIR="/etc/letsencrypt/live/$DOMAIN" ;;
        esac
        if [[ -f "$LIVE_DIR/fullchain.pem" ]]; then
            log "Cert for $DOMAIN already present, skipping."
        else
            log "Obtaining cert for $DOMAIN via Dreamhost DNS-01..."
            log "  This will take ~2-4 minutes (DNS propagation wait)."
            certbot certonly --manual --preferred-challenges dns \
                --manual-auth-hook /opt/docketworks/certbot-hooks/auth.sh \
                --manual-cleanup-hook /opt/docketworks/certbot-hooks/cleanup.sh \
                "${CERTBOT_D[@]}" \
                --non-interactive --agree-tos --email admin@docketworks.site
            log "  Cert obtained for $DOMAIN."
        fi
    done

    # certbot certonly --manual doesn't create the standard SSL config files
    # that the nginx plugin would. Instance nginx configs reference these,
    # so we must ensure they exist whenever this box has any cert at all.
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
fi

# --- Base Nginx config (reject unknown hosts) ---
# The default server returns 444 for any request whose Host doesn't match
# an instance config. Has to reference a real cert for port 443; pick the
# first cert-domain. DR boxes have no certs and so only listen on port 80.

log "Installing base Nginx config (reject unknown hosts)..."
if (( ${#CERT_DOMAINS[@]} > 0 )); then
    FIRST_DOMAIN="${CERT_DOMAINS[0]}"
    case "$FIRST_DOMAIN" in
        \*.*) DEFAULT_LIVE_DIR="${FIRST_DOMAIN#*.}" ;;
        *)    DEFAULT_LIVE_DIR="$FIRST_DOMAIN" ;;
    esac
    cat > /etc/nginx/sites-available/default <<EOF
server {
    listen 80 default_server;
    listen 443 ssl default_server;
    server_name _;

    ssl_certificate /etc/letsencrypt/live/$DEFAULT_LIVE_DIR/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/$DEFAULT_LIVE_DIR/privkey.pem;

    return 444;
}
EOF
else
    cat > /etc/nginx/sites-available/default <<'EOF'
server {
    listen 80 default_server;
    server_name _;
    return 444;
}
EOF
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
PostgreSQL: $(psql --version)
Nginx:      $(nginx -v 2>&1)
Certbot:    $(certbot --version 2>&1)
Git:        $(git --version)
Poetry:     $POETRY_VERSION
pnpm:       $(pnpm --version)
pm2:        $(pm2 --version)
gh:         $(gh --version | head -1)
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
# Same reason as /opt/docketworks above: instance users have no supplementary
# groups and need world-x to traverse into their own instance dir.
chmod 755 /opt/docketworks/instances

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

# --- Install shared Playwright browsers ---

SHARED_PLAYWRIGHT_BROWSERS="/opt/docketworks/.playwright-browsers"
log "Installing shared Playwright browsers to $SHARED_PLAYWRIGHT_BROWSERS..."
# Install system-level browser dependencies as root (apt packages)
PLAYWRIGHT_BROWSERS_PATH="$SHARED_PLAYWRIGHT_BROWSERS" \
    npx --prefix "$LOCAL_REPO/frontend" playwright install-deps chromium
# Install browser binary as the shared service user
sudo -u docketworks bash -c "
    export PLAYWRIGHT_BROWSERS_PATH='$SHARED_PLAYWRIGHT_BROWSERS'
    cd '$LOCAL_REPO/frontend'
    npx playwright install chromium
"
log "  Shared Playwright browsers installed."

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
