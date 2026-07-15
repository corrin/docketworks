#!/usr/bin/env bash
# Pull a production instance's mutable file directories into this checkout's
# local storage roots. This is the file-side companion to pull_prod_backup.sh
# (which pulls the DB) and the restore-side inverse of backup_instance_files.sh
# (which pushes the same dirs to Google Drive); it covers the identical set:
# mediafiles, phone-recordings, session-replays.
#
# A prod DB restore (docs/restore-prod-to-hotfix.md step 4) brings file *paths*,
# not the files, so DB-referenced media/recordings 404 until the bytes are
# copied over. Production stores them under the instance user's home
# (/opt/docketworks/instances/<instance>/), owned by <instance-user> and
# unreadable by the SSH login user -- so rsync runs on the far side as the
# instance user via `sudo -iu`, the same escalation as pull_prod_backup.sh.
# rsync is incremental: re-runs copy only new or changed files.
#
# Usage:
#   scripts/pull_prod_files.sh [host] [instance-user]
#
# Args (both optional; defaults target MSM production):
#   host           SSH target (ssh-config alias or hostname).  Default: MSM
#   instance-user  Unix user owning the instance files remotely.  Default: dw_msm_prod
#
# Env:
#   REMOTE_USER  SSH login user on <host>.  Defaults to the local $USER.
#   MEDIA_ROOT / PHONE_RECORDING_STORAGE_ROOT / SESSION_REPLAY_STORAGE_ROOT
#               Local destinations, read from ./.env when unset.

set -euo pipefail

REMOTE_HOST="${1:-MSM}"
INSTANCE_USER="${2:-dw_msm_prod}"
REMOTE_USER="${REMOTE_USER:-$USER}"

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# Read KEY=value from the repo .env, stripping optional surrounding quotes.
env_val() {
    local key="$1"
    [[ -f "$REPO_ROOT/.env" ]] || return 0
    sed -n "s/^${key}=//p" "$REPO_ROOT/.env" | tail -1 \
        | sed -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'\$//"
}

# Remote subdir (relative to the instance user's home) -> local destination.
declare -A DESTS=(
    [mediafiles]="$(env_val MEDIA_ROOT)"
    [phone-recordings]="$(env_val PHONE_RECORDING_STORAGE_ROOT)"
    [session-replays]="$(env_val SESSION_REPLAY_STORAGE_ROOT)"
)

echo ">> Pulling instance files from $REMOTE_USER@$REMOTE_HOST (owned by $INSTANCE_USER)"
for subdir in mediafiles phone-recordings session-replays; do
    dest="${DESTS[$subdir]}"
    if [[ -z "$dest" ]]; then
        echo "Error: no local destination configured for $subdir (missing .env entry)" >&2
        exit 1
    fi
    echo ">> Syncing $subdir -> $dest"
    mkdir -p "$dest"
    rsync -ah --stats \
        -e ssh \
        --rsync-path="sudo -iu $INSTANCE_USER rsync" \
        "$REMOTE_USER@$REMOTE_HOST:$subdir/" \
        "$dest/"
done
echo ">> Done."
