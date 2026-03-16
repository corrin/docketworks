#!/bin/bash
# Shared constants and helpers for UAT scripts.

DOMAIN="docketworks.site"
BASE_DIR="/opt/docketworks"
INSTANCES_DIR="$BASE_DIR/instances"
SHARED_VENV="$BASE_DIR/.venv"
REPO_URL="https://github.com/corrin/docketworks.git"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a /var/log/docketworks-setup.log
}
