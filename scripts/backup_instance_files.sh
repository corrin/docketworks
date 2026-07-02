#!/bin/bash
set -euo pipefail

# Usage: backup_instance_files.sh <instance>
# Example: backup_instance_files.sh msm-prod

if [[ $# -lt 1 ]]; then
    echo "Usage: $0 <instance>"
    echo "Example: $0 msm-prod"
    exit 1
fi

INSTANCE="$1"
INSTANCE_DIR="/opt/docketworks/instances/$INSTANCE"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SCRIPT_PATH="$SCRIPT_DIR/$(basename "$0")"
EXPECTED_USER="dw_${INSTANCE//-/_}"

if [[ $EUID -eq 0 ]]; then
    exec sudo -u "$EXPECTED_USER" "$SCRIPT_PATH" "$@"
fi

if [[ "$(id -un)" != "$EXPECTED_USER" ]]; then
    echo "Error: file backup for $INSTANCE must run as $EXPECTED_USER" >&2
    exit 1
fi

if [[ ! -d "$INSTANCE_DIR" ]]; then
    echo "Error: instance directory not found: $INSTANCE_DIR" >&2
    exit 1
fi

if [[ -z "${RCLONE_CONFIG:-}" ]]; then
    echo "Error: RCLONE_CONFIG must point at the instance rclone config" >&2
    exit 1
fi

INSTANCE_DIR_REAL="$(readlink -f "$INSTANCE_DIR")"
REMOTE_BASE="gdrive:dw_backups/files"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
ARCHIVE_RETENTION_DAYS=30

backup_dir() {
    local name="$1"
    local local_path="$INSTANCE_DIR/$name"
    local local_real

    if [[ ! -d "$local_path" ]]; then
        echo "Skipping missing directory: $local_path"
        return
    fi
    if [[ -L "$local_path" ]]; then
        echo "Error: refusing to back up symlinked directory: $local_path" >&2
        exit 1
    fi

    local_real="$(readlink -f "$local_path")"
    case "$local_real" in
        "$INSTANCE_DIR_REAL"/*) ;;
        *)
            echo "Error: refusing path outside instance directory: $local_path" >&2
            exit 1
            ;;
    esac

    echo "Syncing $local_path to $REMOTE_BASE/current/$name"
    rclone mkdir "$REMOTE_BASE/current/$name"
    rclone sync \
        "$local_path" \
        "$REMOTE_BASE/current/$name" \
        --backup-dir "$REMOTE_BASE/archive/$TIMESTAMP/$name"
}

prune_old_archives() {
    local cutoff_epoch
    local archives
    local entry
    local name
    local archive_epoch

    rclone mkdir "$REMOTE_BASE/archive"
    archives="$(rclone lsf "$REMOTE_BASE/archive")"
    cutoff_epoch="$(date -d "$ARCHIVE_RETENTION_DAYS days ago" +%s)"

    while IFS= read -r entry; do
        name="${entry%/}"
        if [[ ! "$name" =~ ^[0-9]{8}_[0-9]{6}$ ]]; then
            continue
        fi
        archive_epoch="$(date -d "${name:0:8} ${name:9:2}:${name:11:2}:${name:13:2}" +%s)"
        if (( archive_epoch < cutoff_epoch )); then
            echo "Pruning archived file backup: $REMOTE_BASE/archive/$name"
            rclone purge "$REMOTE_BASE/archive/$name"
        fi
    done <<< "$archives"
}

backup_dir "phone-recordings"
backup_dir "session-replays"
backup_dir "mediafiles"
prune_old_archives
