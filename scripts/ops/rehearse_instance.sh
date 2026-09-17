#!/usr/bin/env bash
# Run `instance.sh rehearse` on the UAT host from this machine (ADR 0066;
# docs/server_setup.md, Part E). The host's output streams here and into
# logs/rehearsals/<timestamp>.log; the exit status is the host's.
#
# Usage:
#   scripts/ops/rehearse_instance.sh <host> <client> [--ref <ref>]
#
# Args:
#   <host>    SSH target (an ssh-config alias or hostname).
#   <client>  The rehearsal client name, e.g. rehearsal; the instance is
#             <client>-uat and its three config files must already exist on
#             the host (docs/server_setup.md, Part E).
#   --ref     Release ref to create from; defaults to origin/main on the host.
#
# Env:
#   REMOTE_USER  SSH login user on <host>. Defaults to the local $USER.

set -euo pipefail

usage() {
    echo "Usage: $0 <host> <client> [--ref <ref>]" >&2
    exit 2
}

if [[ $# -lt 2 ]]; then
    usage
fi

REMOTE_HOST="$1"
CLIENT="$2"
shift 2
REF=""
while (($#)); do
    case "$1" in
        --ref)
            [[ $# -ge 2 ]] || usage
            REF="$2"
            shift 2
            ;;
        *) usage ;;
    esac
done
REMOTE_USER="${REMOTE_USER:-$USER}"

# Both values are interpolated into the remote command (client-side
# expansion is the point of the SC2029 waiver below), so anything beyond a
# client name or a git ref could execute on the host before sudo runs.
if [[ ! "$CLIENT" =~ ^[a-z0-9]+$ ]]; then
    echo "ERROR: client must be lowercase alphanumeric (got: $CLIENT)" >&2
    exit 2
fi
if [[ -n "$REF" && ! "$REF" =~ ^[A-Za-z0-9_./-]+$ ]]; then
    echo "ERROR: ref must be a plain git ref (got: $REF)" >&2
    exit 2
fi

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
LOG_DIR="$REPO_ROOT/logs/rehearsals"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/$(date +%Y%m%d_%H%M%S).log"

REMOTE_COMMAND="sudo /opt/docketworks/repo/scripts/server/instance.sh rehearse $CLIENT"
if [[ -n "$REF" ]]; then
    REMOTE_COMMAND+=" --ref $REF"
fi

echo ">> Rehearsing $CLIENT-uat on $REMOTE_HOST${REF:+ from $REF}; log: $LOG"
# shellcheck disable=SC2029  # values are meant to expand client-side
ssh -t "$REMOTE_USER@$REMOTE_HOST" "$REMOTE_COMMAND" 2>&1 | tee "$LOG"
# tee's status is the pipeline's; the host's is what this run reports.
status="${PIPESTATUS[0]}"

echo ">> $(tail -n1 "$LOG")"
echo ">> log: $LOG"
exit "$status"
