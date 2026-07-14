#!/usr/bin/env bash
# Pull a fresh scrubbed prod backup from a remote instance into ./restore/.
#
# Runs `manage.py backport_data_backup --output /tmp/<name>` on the remote as
# the instance user, then scps the resulting dump into the local restore dir.
#
# Usage:
#   scripts/pull_prod_backup.sh <host> <instance-user>
#
# Args:
#   <host>           SSH target (e.g. an ssh-config alias or hostname).
#   <instance-user>  Unix user that owns the instance's venv + DB role on the
#                    remote (e.g. dw_<instance>_<env>). Also used as the
#                    DB-name token in the dump filename, matching the
#                    convention used by backport_data_backup.
#
# Env:
#   REMOTE_USER  SSH login user on <host>. Defaults to the local $USER.

set -euo pipefail

if [[ $# -ne 2 ]]; then
    echo "Usage: $0 <host> <instance-user>" >&2
    exit 2
fi

REMOTE_HOST="$1"
INSTANCE_USER="$2"
REMOTE_USER="${REMOTE_USER:-$USER}"

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOCAL_DIR="$REPO_ROOT/restore"

if [[ ! -d "$LOCAL_DIR" ]]; then
    echo "Local restore dir not found: $LOCAL_DIR" >&2
    exit 1
fi

TS="$(date +%Y%m%d_%H%M%S)"
DUMP_NAME="scrubbed_${INSTANCE_USER}_${TS}.dump"
TMP_PATH="/tmp/$DUMP_NAME"
LOCAL_PATH="$LOCAL_DIR/$DUMP_NAME"
REMOTE_STAGED=false
LOCAL_COPIED=false

cleanup() {
    local command_status=$?
    local cleanup_status=0
    trap - EXIT
    set +e

    if [[ "$REMOTE_STAGED" == true ]]; then
        echo ">> Removing remote staging file..."
        # Dump is owned by $INSTANCE_USER and /tmp has the sticky bit, so the
        # delete has to run as the same user that created it.
        # shellcheck disable=SC2029  # values are meant to expand client-side
        ssh "$REMOTE_USER@$REMOTE_HOST" "sudo -u $INSTANCE_USER rm -f '$TMP_PATH'"
        cleanup_status=$?
    fi

    if [[ $command_status -ne 0 && "$LOCAL_COPIED" == true ]]; then
        echo ">> Removing failed local backup..." >&2
        rm -f "$LOCAL_PATH"
    fi

    if [[ $command_status -ne 0 ]]; then
        exit "$command_status"
    fi
    exit "$cleanup_status"
}

trap cleanup EXIT

echo ">> Generating $DUMP_NAME on $REMOTE_HOST as $INSTANCE_USER..."
REMOTE_STAGED=true
# shellcheck disable=SC2029  # values are meant to expand client-side
ssh "$REMOTE_USER@$REMOTE_HOST" \
    "sudo -iu $INSTANCE_USER bash -lc 'cd app && python manage.py backport_data_backup --output $TMP_PATH'"

echo ">> Copying $DUMP_NAME to $LOCAL_DIR/..."
LOCAL_COPIED=true
scp "$REMOTE_USER@$REMOTE_HOST:$TMP_PATH" "$LOCAL_DIR/"

echo ">> Verifying scrubbed backup..."
python "$REPO_ROOT/scripts/verify_scrubbed_backup.py" "$LOCAL_PATH"

echo ">> SHA-256: $(sha256sum "$LOCAL_PATH" | cut -d' ' -f1)"
echo ">> Done: $LOCAL_PATH"
