#!/bin/bash
set -euo pipefail

# TEMPORARY v1->v2 cutover, host step. Run once per host, before any
# cutover-instance.sh. See README.md in this directory; delete the whole
# directory after both hosts are migrated.
#
# Usage: cutover-host.sh [--allow-port <port> ...]
#
# --allow-port: acknowledge a public listener beyond 22/80/443 that is
# expected to keep working through provider/network-level rules (or to
# be intentionally dropped). Without it, an unexpected public listener
# aborts the cutover before any state changes.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVER_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
# shellcheck source=../common.sh
source "$SERVER_DIR/common.sh"

if [[ $EUID -ne 0 ]]; then
    echo "ERROR: This script must be run as root (use sudo)." >&2
    exit 1
fi

ALLOWED_EXTRA_PORTS=()
if ! parsed=$(getopt -o '' --long allow-port: -n "$(basename "$0")" -- "$@"); then
    echo "Usage: $0 [--allow-port <port> ...]" >&2
    exit 1
fi
eval set -- "$parsed"
while true; do
    case "$1" in
        --allow-port) ALLOWED_EXTRA_PORTS+=("$2"); shift 2 ;;
        --) shift; break ;;
    esac
done

STATE_DIR="/opt/docketworks/cutover-state/host-$(date +%Y%m%d_%H%M%S)"
mkdir -p "$STATE_DIR"
chmod 700 "$STATE_DIR"
ln -sfn "$STATE_DIR" /opt/docketworks/cutover-state/host-latest

log "=========================================="
log "v1->v2 HOST cutover starting; state recorded in $STATE_DIR"
log "=========================================="

# --- Record everything the rollback path or a post-mortem could need ---
iptables-save > "$STATE_DIR/iptables-save.txt"
ip6tables-save > "$STATE_DIR/ip6tables-save.txt" 2>/dev/null || true
ss -tlnp > "$STATE_DIR/listeners.txt"
systemctl list-units --type=service --all 'gunicorn-*' 'celery-*' \
    > "$STATE_DIR/services.txt" 2>/dev/null || true
git -C "$LOCAL_REPO" remote get-url origin > "$STATE_DIR/repo-remote.txt"
git -C "$LOCAL_REPO" rev-parse HEAD > "$STATE_DIR/repo-head.txt"
systemctl is-enabled netfilter-persistent > "$STATE_DIR/netfilter-enabled.txt" 2>/dev/null || true

# --- Refuse if an unexpected PUBLIC listener would lose reachability ---
# UFW ends with only 22/80/443 open. Loopback listeners (gunicorn sockets
# are unix sockets anyway; the marketing site's pm2 port sits behind
# nginx) are unaffected — only wildcard/public binds matter.
UNEXPECTED=()
while read -r port; do
    case "$port" in
        22|80|443) continue ;;
    esac
    if [[ " ${ALLOWED_EXTRA_PORTS[*]-} " == *" $port "* ]]; then
        log "Acknowledged public listener on port $port (--allow-port)."
        continue
    fi
    UNEXPECTED+=("$port")
done < <(ss -tlnH | awk '{print $4}' | grep -E '^(0\.0\.0\.0|\*|\[::\]):' | sed 's/.*://' | sort -un)

if (( ${#UNEXPECTED[@]} > 0 )); then
    echo "ERROR: Public listeners beyond 22/80/443 would be firewalled off:" >&2
    for p in "${UNEXPECTED[@]}"; do
        ss -tlnp | awk -v p=":$p" '$4 ~ p"$"' >&2
    done
    echo "  Re-run with --allow-port <port> for each one that is expected." >&2
    exit 1
fi
log "Public listener check passed (only 22/80/443 exposed after UFW)."

# --- Swap the shared repo to the v2 remote ---
# remote set-url (not re-clone): v1's objects and the recorded HEAD stay
# available for rollback, and running v1 instances never touch the repo —
# they run from immutable release directories.
if [[ -n "$(git -C "$LOCAL_REPO" status --porcelain)" ]]; then
    echo "ERROR: $LOCAL_REPO has local modifications — it must be a clean, pull-only clone." >&2
    exit 1
fi
CURRENT_REMOTE="$(git -C "$LOCAL_REPO" remote get-url origin)"
if [[ "$CURRENT_REMOTE" == "$REMOTE_REPO_URL" ]]; then
    log "Repo already points at $REMOTE_REPO_URL; skipping remote swap."
else
    log "Swapping repo remote: $CURRENT_REMOTE -> $REMOTE_REPO_URL"
    sudo -u docketworks git -C "$LOCAL_REPO" remote set-url origin "$REMOTE_REPO_URL"
fi
sudo -u docketworks git -C "$LOCAL_REPO" fetch --prune origin
# Align the checked-out branch to v2's main: v1's HEAD is not an ancestor
# of v2's, so the plain --ff-only pull in server-setup.sh would refuse.
sudo -u docketworks git -C "$LOCAL_REPO" checkout -B main origin/main

# --- Retire the legacy firewall, then converge the host ---
# server-setup.sh refuses to enable UFW while netfilter-persistent is
# enabled (two owners of the same tables). The legacy rules are recorded
# above; flushing to policy ACCEPT leaves a seconds-long open window
# inside the maintenance window, upstream provider network rules
# permitting, before UFW's default-deny takes over.
if systemctl is-enabled --quiet netfilter-persistent 2>/dev/null; then
    log "Disabling netfilter-persistent (rules recorded in $STATE_DIR)..."
    systemctl disable --now netfilter-persistent
fi
iptables -P INPUT ACCEPT
iptables -F INPUT
ip6tables -P INPUT ACCEPT 2>/dev/null || true
ip6tables -F INPUT 2>/dev/null || true

log "Converging host via server-setup.sh (UFW, fail2ban, uv, v2 repo)..."
bash "$SERVER_DIR/server-setup.sh"

log "=========================================="
log "HOST cutover complete."
log "  Next, per instance:"
log "    sudo $SCRIPT_DIR/cutover-instance.sh <client> <env> [--ref <ref>]"
log "=========================================="
