#!/bin/bash
set -euo pipefail

# Verify an instance's full serving path: systemd units, the build-id
# endpoint through nginx+TLS, the auth gate, media serving, backup
# timers, and the host security posture (UFW + fail2ban jails). Safe to
# run at any time; run it after any deploy or configuration change.
#
# Usage: verify-instance.sh <client> <env>

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"
# shellcheck source=release-utils.sh
source "$SCRIPT_DIR/release-utils.sh"

if [[ $EUID -ne 0 ]]; then
    echo "ERROR: This script must be run as root (use sudo)." >&2
    exit 1
fi

if [[ $# -ne 2 ]]; then
    echo "Usage: $0 <client> <env>" >&2
    exit 1
fi
CLIENT="$1"
ENV="$2"
validate_env "$ENV"
INSTANCE="${CLIENT}-${ENV}"
INSTANCE_DIR="$INSTANCES_DIR/$INSTANCE"

FAILURES=0
# --verbose keeps the command's own output (diagnostic checks name their
# failing integration); default suppresses it (binary checks).
check() {
    local verbose=false
    if [[ "$1" == "--verbose" ]]; then
        verbose=true
        shift
    fi
    local label="$1"
    shift
    if [[ "$verbose" == "true" ]]; then
        echo "CHECK: $label"
    fi
    local result=0
    if [[ "$verbose" == "true" ]]; then
        "$@" || result=1
    else
        "$@" >/dev/null 2>&1 || result=1
    fi
    if [[ "$result" -eq 0 ]]; then
        echo "PASS: $label"
    else
        echo "FAIL: $label"
        FAILURES=$((FAILURES + 1))
    fi
}

FQDN_FILE="$INSTANCE_DIR/.fqdn"
if [[ -f "$FQDN_FILE" ]]; then
    FQDN="$(cat "$FQDN_FILE")"
else
    FQDN="$INSTANCE.$DOMAIN"
fi
# --resolve pins the FQDN to this host so verification never depends on
# DNS having cut over yet; the certificate still validates because the
# name matches.
CURL=(curl -sS --max-time 15 --resolve "$FQDN:443:127.0.0.1")

# --- Services ---
# Fable: bare is-active cannot see a crash loop — with Restart=always and
# RestartSec=10 a unit that dies on startup is "active" for a slice of
# every cycle, which is how a beat crash-looping on its schedule file
# verified green on UAT. NRestarts must also hold still across a window
# longer than every unit's RestartSec (10s beat/worker, 5s gunicorn), so
# a loop is forced to tick at least once inside it.
RUNTIME_UNITS=("gunicorn-$INSTANCE" "celery-worker-$INSTANCE" "celery-beat-$INSTANCE")
declare -A NRESTARTS_BEFORE
for unit in "${RUNTIME_UNITS[@]}"; do
    NRESTARTS_BEFORE[$unit]="$(systemctl show "$unit" -p NRestarts --value)"
done
sleep 12
unit_running_stably() {
    local unit="$1"
    systemctl is-active --quiet "$unit" || return 1
    [[ "$(systemctl show "$unit" -p NRestarts --value)" == "${NRESTARTS_BEFORE[$unit]}" ]]
}
check "gunicorn-$INSTANCE active and stable" unit_running_stably "gunicorn-$INSTANCE"
check "celery-worker-$INSTANCE active and stable" unit_running_stably "celery-worker-$INSTANCE"
check "celery-beat-$INSTANCE active and stable" unit_running_stably "celery-beat-$INSTANCE"

# --- Serving path: build-id through nginx+TLS must match the release link ---
# Retried: this is the first HTTP probe after a restart, and gunicorn may
# not have bound its socket yet — a race, not a failure.
EXPECTED_SHA="$(instance_current_sha "$INSTANCE")"
BUILD_ID=""
for _ in 1 2 3 4 5 6 7 8 9 10; do
    BUILD_ID="$("${CURL[@]}" "https://$FQDN/api/build-id/" 2>/dev/null | python3 -c 'import json,sys; print(json.load(sys.stdin)["build_id"])' 2>/dev/null || true)"
    [[ -n "$BUILD_ID" ]] && break
    sleep 2
done
if [[ -n "$BUILD_ID" && "$BUILD_ID" == "$EXPECTED_SHA" ]]; then
    echo "PASS: /api/build-id/ serves the linked release ($(short_release_sha "$BUILD_ID"))"
else
    echo "FAIL: /api/build-id/ returned '${BUILD_ID:-<nothing>}', expected $EXPECTED_SHA"
    FAILURES=$((FAILURES + 1))
fi

# --- Auth gate: a protected endpoint refuses anonymous requests ---
# status-choices is a stable authenticated GET (a bare GET /api/job/jobs/
# does not exist — the collection route is POST-only).
STATUS="$("${CURL[@]}" -o /dev/null -w '%{http_code}' "https://$FQDN/api/job/jobs/status-choices/")"
if [[ "$STATUS" == "401" ]]; then
    echo "PASS: anonymous /api/job/jobs/status-choices/ is refused (401)"
else
    echo "FAIL: anonymous /api/job/jobs/status-choices/ returned $STATUS, expected 401"
    FAILURES=$((FAILURES + 1))
fi

# --- Media location: nginx serves MEDIA_ROOT directly ---
# A real probe file must come back byte-identical: a bare 404 check could
# false-PASS if some proxied route also answered 404. Cleaned up after.
PROBE_NAME=".verify-media-probe-$$.txt"
PROBE_PATH="$INSTANCE_DIR/mediafiles/$PROBE_NAME"
PROBE_CONTENT="verify-instance media probe $$"
echo "$PROBE_CONTENT" > "$PROBE_PATH"
chown "$(instance_user "$INSTANCE"):www-data" "$PROBE_PATH"
chmod 640 "$PROBE_PATH"
SERVED="$("${CURL[@]}" "https://$FQDN/media/$PROBE_NAME" || true)"
rm -f "$PROBE_PATH"
if [[ "$SERVED" == "$PROBE_CONTENT" ]]; then
    echo "PASS: /media/ serves MEDIA_ROOT (probe file round-tripped)"
else
    echo "FAIL: /media/ probe served '${SERVED:0:60}', expected the probe file"
    FAILURES=$((FAILURES + 1))
fi

# --- SPA entry point ---
STATUS="$("${CURL[@]}" -o /dev/null -w '%{http_code}' "https://$FQDN/index.html")"
if [[ "$STATUS" == "200" ]]; then
    echo "PASS: SPA index.html serves (200)"
else
    echo "FAIL: /index.html returned $STATUS, expected 200"
    FAILURES=$((FAILURES + 1))
fi

# --- Database-backed integrations ---
# Codex: the permanent verifier's final all-clear includes the live services
# the instance is configured to use and preserves their diagnostic output; a
# blank key and an upstream refusal must name the failing integration instead
# of collapsing into an unexplained green cutover.
# Every JobFile row's bytes must exist under DROPBOX_WORKFLOW_FOLDER.
# Process liveness cannot catch the failure class this guards: a root
# pointed one directory too high 404s every attachment while Dropbox
# sync, systemd and disk all report healthy (2026-08-31 production
# incident — the media probe above only proves MEDIA_ROOT).
check --verbose "JobFile attachments resolve on disk" \
    "$SCRIPT_DIR/dw-run.sh" "$INSTANCE" \
    python -m scripts.ops.restore_checks.check_jobfiles

check --verbose "IntegrationSettings live connections" \
    "$SCRIPT_DIR/dw-run.sh" "$INSTANCE" \
    python -m scripts.ops.restore_checks.check_integration_settings

# --- Host security posture ---
check "UFW active" bash -c "ufw status | grep -q '^Status: active'"
check "fail2ban jail sshd" fail2ban-client status sshd
check "fail2ban jail docketworks-auth-login" fail2ban-client status docketworks-auth-login
check "fail2ban jail docketworks-auth-refresh" fail2ban-client status docketworks-auth-refresh
check "nginx config valid" nginx -t
check "backup-db-$INSTANCE.timer active" systemctl is-active --quiet "backup-db-$INSTANCE.timer"
check "backup-files-$INSTANCE.timer active" systemctl is-active --quiet "backup-files-$INSTANCE.timer"

# --- Backup upload path ---
# Fable: an active timer proves nothing about the remote: prod's unit was red every
# night for months on a zero-quota service-account remote while a root cron
# quietly did the real uploads. Round-trip one probe file exactly the way
# the nightly unit uploads — same user, same RCLONE_CONFIG — so a remote
# that cannot receive an upload fails verification here, not at 03:05.
INSTANCE_USER="$(instance_user "$INSTANCE")"
RCLONE_CONF="$(instance_rclone_config "$INSTANCE")"
# System python3 like cleanup_backups.sh: the module is stdlib-only, and
# importing the constant keeps the remote defined in exactly one place.
REMOTE_BASE="$(python3 -c 'import sys; sys.path.insert(0, sys.argv[1]); from cleanup_backups import REMOTE_BASE; print(REMOTE_BASE)' "$SCRIPT_DIR/..")"
PROBE_NAME="verify_probe_${INSTANCE}_$(date +%Y%m%d_%H%M%S)"
PROBE_LOCAL="$(sudo -u "$INSTANCE_USER" mktemp "/tmp/$PROBE_NAME.XXXXXX")"
backup_upload_probe() {
    sudo -u "$INSTANCE_USER" env RCLONE_CONFIG="$RCLONE_CONF" \
        rclone copyto "$PROBE_LOCAL" "$REMOTE_BASE/$PROBE_NAME" \
    && sudo -u "$INSTANCE_USER" env RCLONE_CONFIG="$RCLONE_CONF" \
        rclone deletefile "$REMOTE_BASE/$PROBE_NAME"
}
check "backup remote accepts an upload as $INSTANCE_USER" backup_upload_probe
sudo -u "$INSTANCE_USER" rm -f "$PROBE_LOCAL"

# --- Runtime units: still stable after the full verification run ---
# Fable: the 12s window catches only a fast crash loop; a unit that dies
# tens of seconds in outlives it. Rechecking the same baselines here
# stretches the observed window to the whole verifier run. A readiness
# signal was the rejected alternative: celery ships no sd_notify support,
# so Type=notify cannot cover beat or the worker.
for unit in "${RUNTIME_UNITS[@]}"; do
    check "$unit stable through verification" unit_running_stably "$unit"
done

echo ""
if (( FAILURES > 0 )); then
    echo "$FAILURES verification check(s) FAILED for $INSTANCE."
    exit 1
fi
echo "All verification checks passed for $INSTANCE."
