#!/bin/bash
set -euo pipefail

# Run a command as an instance user with the shared venv and instance .env loaded.
#
# Usage: dw-run <instance> <command> [args...]
# Examples:
#   dw-run msm-uat python manage.py migrate --no-input
#   dw-run msm-uat python manage.py loaddata demo_fixtures
#   dw-run msm-uat python scripts/setup_dev_logins.py

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/common.sh"

if [[ $# -lt 2 ]]; then
    echo "Usage: $0 <instance> <command> [args...]"
    echo "Example: $0 msm-uat python manage.py migrate --no-input"
    exit 1
fi

INSTANCE="$1"
shift
INSTANCE_DIR="$INSTANCES_DIR/$INSTANCE"
INSTANCE_USER="$(instance_user "$INSTANCE")"

if [[ ! -d "$INSTANCE_DIR" ]]; then
    echo "ERROR: Instance directory $INSTANCE_DIR does not exist." >&2
    exit 1
fi

if [[ ! -f "$INSTANCE_DIR/.env" ]]; then
    echo "ERROR: No .env file found at $INSTANCE_DIR/.env" >&2
    exit 1
fi

# Build the command string with proper escaping
# Instance dir IS the git checkout, so cd there directly.
CMD="source '$SHARED_VENV/bin/activate'
set -a
source '$INSTANCE_DIR/.env'
set +a
cd '$INSTANCE_DIR'
$(printf '%q ' "$@")"

exec sudo -u "$INSTANCE_USER" bash -c "$CMD"
