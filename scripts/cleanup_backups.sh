#!/usr/bin/env bash
set -euo pipefail

# Usage: cleanup_backups.sh <instance> [--delete]
# Example: cleanup_backups.sh msm --delete

if [[ $# -lt 1 ]]; then
    echo "Usage: $0 <instance> [--delete]"
    echo "Example: $0 msm --delete"
    exit 1
fi

INSTANCE="$1"
shift
BACKUP_DIR="/opt/docketworks/instances/$INSTANCE/backups"

source /opt/docketworks/.venv/bin/activate
exec python "$(dirname "$0")/cleanup_backups.py" "$BACKUP_DIR" "$@"
