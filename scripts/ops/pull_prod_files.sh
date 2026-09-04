#!/usr/bin/env bash
# Pull a production instance's mutable file directories into this checkout's
# local storage roots. The file-side companion to pull_prod_backup.sh (which
# pulls the DB) and the restore-side inverse of backup_instance_files.sh (which
# pushes the same dirs to Google Drive); it covers the identical set:
# mediafiles, phone-recordings, session-replays.
#
# A prod DB restore brings file *paths*, not the files, so DB-referenced media,
# call recordings and replay chunks resolve to nothing until the bytes are
# copied over. Production stores them under the instance user's home
# (/opt/docketworks/instances/<instance>/), owned by <instance-user> and
# unreadable by the SSH login user — so rsync runs on the far side as the
# instance user via `sudo -iu`, the same escalation as pull_prod_backup.sh.
# rsync is incremental: re-runs copy only new or changed files.
#
# Usage:
#   scripts/ops/pull_prod_files.sh <host> <instance-user>
#
# Args:
#   <host>           SSH target (an ssh-config alias or hostname).
#   <instance-user>  Unix user owning the instance files remotely
#                    (e.g. dw_<instance>_<env>).
#
# Env:
#   REMOTE_USER  SSH login user on <host>. Defaults to the local $USER.
#   MEDIA_ROOT / PHONE_RECORDING_STORAGE_ROOT / SESSION_REPLAY_STORAGE_ROOT
#               Local destinations. Read from ./.env when unset.

set -euo pipefail

if [[ $# -ne 2 ]]; then
    echo "Usage: $0 <host> <instance-user>" >&2
    exit 2
fi

REMOTE_HOST="$1"
INSTANCE_USER="$2"
REMOTE_USER="${REMOTE_USER:-$USER}"

# INSTANCE_USER is interpolated into the remote --rsync-path command, so
# anything beyond a plain unix account name could execute on the remote host
# before sudo runs. Same guard, same reason, as pull_prod_backup.sh.
if [[ ! "$INSTANCE_USER" =~ ^[a-z_][a-z0-9_-]*$ ]]; then
    echo "ERROR: instance-user must be a plain unix account name (got: $INSTANCE_USER)" >&2
    exit 2
fi

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

# Read KEY=value from the repo .env, stripping optional surrounding quotes.
# Parsed rather than sourced: .env is consumed by load_dotenv() everywhere else,
# and sourcing it would execute whatever a stray backtick or $( ) contained.
env_val() {
    local key="$1"
    [[ -f "$REPO_ROOT/.env" ]] || return 0
    sed -n "s/^${key}=//p" "$REPO_ROOT/.env" | tail -1 \
        | sed -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'\$//"
}

# Remote subdir (relative to the instance user's home) -> local destination.
declare -A DESTS=(
    [mediafiles]="${MEDIA_ROOT:-$(env_val MEDIA_ROOT)}"
    [phone-recordings]="${PHONE_RECORDING_STORAGE_ROOT:-$(env_val PHONE_RECORDING_STORAGE_ROOT)}"
    [session-replays]="${SESSION_REPLAY_STORAGE_ROOT:-$(env_val SESSION_REPLAY_STORAGE_ROOT)}"
)

# Every destination is resolved before the first byte moves: a missing root
# discovered halfway through leaves a partial pull that looks like a complete
# one on the dirs it did reach.
for subdir in mediafiles phone-recordings session-replays; do
    if [[ -z "${DESTS[$subdir]}" ]]; then
        echo "ERROR: no local destination for $subdir (set it in .env or the environment)" >&2
        exit 1
    fi
done

echo ">> Pulling instance files from $REMOTE_USER@$REMOTE_HOST (owned by $INSTANCE_USER)"
for subdir in mediafiles phone-recordings session-replays; do
    dest="${DESTS[$subdir]}"
    echo ">> Syncing $subdir -> $dest"
    mkdir -p "$dest"
    rsync -ah --stats \
        -e ssh \
        --rsync-path="sudo -iu $INSTANCE_USER rsync" \
        "$REMOTE_USER@$REMOTE_HOST:$subdir/" \
        "$dest/"
done
echo ">> Done."
