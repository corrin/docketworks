#!/bin/bash
# Shared constants and helpers for UAT scripts.

DOMAIN="docketworks.site"
BASE_DIR="/opt/docketworks"
INSTANCES_DIR="$BASE_DIR/instances"
CONFIG_DIR="$BASE_DIR/config"
SHARED_VENV="$BASE_DIR/.venv"
LOCAL_REPO="$BASE_DIR/repo"
REMOTE_REPO_URL="https://github.com/corrin/docketworks.git"

VALID_ENVS="dev uat staging prod"

# Per-instance disk quotas (requires filesystem quotas enabled on /opt or /)
QUOTA_SOFT="2G"
QUOTA_HARD="5G"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a /var/log/docketworks-setup.log
}

validate_env() {
    local env="$1"
    for valid in $VALID_ENVS; do
        [[ "$env" == "$valid" ]] && return 0
    done
    echo "ERROR: Invalid environment '$env'. Must be one of: $VALID_ENVS"
    exit 1
}
