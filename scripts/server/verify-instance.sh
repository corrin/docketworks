#!/bin/bash
set -euo pipefail

# Verify an instance's full serving path: systemd units, the build-id
# endpoint through nginx+TLS, the auth gate, media serving, backup
# timers, and the host security posture (UFW + fail2ban jails). Safe to
# run at any time; run it after any deploy or configuration change.
#
# --e2e first runs the E2E suite against the instance at its own domain, on
# a copy of its database held in the scrub database, with the fake Xero
# (ADR 0064): users are fenced out for the run, the copy is emptied
# afterwards, and the live database is only ever read. The instance is
# offline for the run, so a prod instance requires --production as well.
#
# Usage: verify-instance.sh <client> <env> [--e2e [--production] [-- <playwright args>]]

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"
# shellcheck source=release-utils.sh
source "$SCRIPT_DIR/release-utils.sh"

if [[ $EUID -ne 0 ]]; then
    echo "ERROR: This script must be run as root (use sudo)." >&2
    exit 1
fi

usage() {
    echo "Usage: $0 <client> <env> [--e2e [--production] [-- <playwright args>]]" >&2
    exit 1
}
if [[ $# -lt 2 ]]; then
    usage
fi
CLIENT="$1"
ENV="$2"
shift 2
E2E=false
PRODUCTION=false
PLAYWRIGHT_ARGS=()
while (($#)); do
    case "$1" in
        --e2e) E2E=true ;;
        --production) PRODUCTION=true ;;
        --) shift; PLAYWRIGHT_ARGS=("$@"); break ;;
        *) usage ;;
    esac
    shift
done
validate_env "$ENV"
INSTANCE="${CLIENT}-${ENV}"
INSTANCE_DIR="$INSTANCES_DIR/$INSTANCE"
INSTANCE_USER="$(instance_user "$INSTANCE")"
if [[ "$PRODUCTION" == "true" && "$E2E" == "false" ]]; then
    echo "ERROR: --production only qualifies --e2e." >&2
    exit 1
fi
if [[ "$E2E" == "true" && "$ENV" == "prod" && "$PRODUCTION" == "false" ]]; then
    echo "ERROR: --e2e takes $INSTANCE offline for the run; pass --production to say so (ADR 0048)." >&2
    exit 1
fi
if [[ "$PRODUCTION" == "true" && "$ENV" != "prod" ]]; then
    echo "ERROR: --production is for a prod instance; $INSTANCE is not one." >&2
    exit 1
fi

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

wait_for_build_id() {
    # Retried: the first HTTP probe after a restart, and gunicorn may not
    # have bound its socket yet — a race, not a failure.
    for _ in 1 2 3 4 5 6 7 8 9 10; do
        BUILD_ID="$("${CURL[@]}" "https://$FQDN/api/build-id/" 2>/dev/null | python3 -c 'import json,sys; print(json.load(sys.stdin)["build_id"])' 2>/dev/null || true)"
        [[ -n "$BUILD_ID" ]] && return 0
        sleep 2
    done
    return 1
}

# --- E2E on a copy of the database (ADR 0064) ---
E2E_STATUS=0
if [[ "$E2E" == "true" ]]; then
    E2E_DIR="$INSTANCE_DIR/e2e"
    E2E_ENV="$E2E_DIR/env"
    FENCE="$E2E_DIR/fence.conf"
    E2E_CREDENTIALS="$CONFIG_DIR/$INSTANCE.e2e.env"
    RELEASE_DIR="$(readlink -f "$INSTANCE_DIR/app")"
    PLAYWRIGHT_BROWSERS_PATH="$BASE_DIR/.playwright"
    export PLAYWRIGHT_BROWSERS_PATH
    RUNTIME_UNIT_NAMES=(gunicorn celery-worker celery-beat)
    # shellcheck disable=SC2034  # instance_db_names assigns all five; only SCRUB_DB_NAME and DB_NAME are read here
    DB_NAME="" DB_USER="" SCRUB_DB_NAME="" TEST_DB_USER="" TEST_DB_NAME=""
    instance_db_names "$CLIENT" "$ENV"

    if [[ -f "$INSTANCE_DIR/.dr-mode" ]]; then
        echo "ERROR: $INSTANCE is a DR standby (.dr-mode); it serves nothing to verify." >&2
        exit 1
    fi
    require_root_owned_credentials_file "$E2E_CREDENTIALS"
    # The same lock deploy.sh takes: a deploy mid-run would migrate the live
    # database under the copy's nose, and this run would restart the units
    # under a deploy's feet.
    take_deploy_lock() {
        exec 9>"$BASE_DIR/.deploy.lock"
        flock -n 9
    }
    if ! take_deploy_lock; then
        echo "ERROR: a deploy is in progress (lock $BASE_DIR/.deploy.lock); run again after it." >&2
        exit 1
    fi

    E2E_RESTORED=false
    e2e_restore_instance() {
        # Always runs, whatever happened to the run: the instance comes back.
        [[ "$E2E_RESTORED" == "true" ]] && return 0
        E2E_RESTORED=true
        set +e
        echo "E2E: returning $INSTANCE to its live database..."
        systemctl stop "celery-worker-$INSTANCE" "gunicorn-$INSTANCE"
        # A task the last spec queued must not run against the live database
        # with the real transport.
        "$SCRIPT_DIR/dw-run.sh" "$INSTANCE" celery -A config purge -f >/dev/null
        local unit
        for unit in "${RUNTIME_UNIT_NAMES[@]}"; do
            rm -f "/run/systemd/system/$unit-$INSTANCE.service.d/e2e.conf"
            rmdir "/run/systemd/system/$unit-$INSTANCE.service.d" 2>/dev/null
        done
        systemctl daemon-reload
        systemctl start "celery-worker-$INSTANCE" "celery-beat-$INSTANCE" "gunicorn-$INSTANCE"
        # CompanyDefaults edits a spec made sit in the shared Redis under this
        # instance's prefix for SOLO_CACHE_TIMEOUT (300s, config/settings.py);
        # real users must not read them, and cache.clear() would empty every
        # instance's cache, so the fence stays up until they have expired.
        echo "E2E: fence stays up 300s for the solo cache to expire..."
        sleep 300
        "$SCRIPT_DIR/dw-run.sh" "$INSTANCE" python manage.py scrub_copy empty >/dev/null
        rm -rf "${E2E_DIR:?}/media" "${E2E_DIR:?}/phone-recordings" "${E2E_DIR:?}/session-replays" "${E2E_DIR:?}/tmp"
        rm -f "$FENCE"
        nginx -t && systemctl reload nginx
        flock -u 9
        set -e
    }
    trap e2e_restore_instance EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM

    # The browser and the harness reach the instance at its own domain, on
    # this box: an IPv4 hosts entry, because the box need not hairpin its
    # public address (the curls above pin it the same way with --resolve).
    if ! grep -qE "^127\.0\.0\.1[[:space:]]+$FQDN([[:space:]]|$)" /etc/hosts; then
        echo "127.0.0.1 $FQDN # verify-instance.sh --e2e" >> /etc/hosts
    fi

    # Playwright and its browser. The release's node_modules were removed
    # after its build (release-utils.sh); the browser lives beside the
    # releases, shared and readable by every instance user.
    if [[ ! -d "$RELEASE_DIR/frontend/node_modules" ]]; then
        echo "E2E: installing the release's frontend dev dependencies..."
        sudo -u docketworks npm ci --prefix "$RELEASE_DIR/frontend" --include=dev --cache "$BASE_DIR/.npm-cache"
    fi
    "$RELEASE_DIR/frontend/node_modules/.bin/playwright" install --with-deps chromium
    chmod -R a+rX "$PLAYWRIGHT_BROWSERS_PATH"

    # The window env: the instance's own, then the lines that win over it in
    # both `source` and systemd's EnvironmentFile= — the copy as DB_NAME, the
    # fake, this run's own temp and storage roots, and the E2E credentials.
    rm -rf "${E2E_DIR:?}/tmp" "${E2E_DIR:?}/media" "${E2E_DIR:?}/phone-recordings" "${E2E_DIR:?}/session-replays"
    mkdir -p "$E2E_DIR"/{tmp,media,phone-recordings,session-replays}
    {
        cat "$INSTANCE_DIR/.env"
        echo
        echo "# --- verify-instance.sh --e2e window (ADR 0064): later lines win ---"
        echo "DB_NAME=$SCRUB_DB_NAME"
        echo "SCRUB_DB_NAME="
        echo "XERO_FAKE=true"
        echo "TMPDIR=$E2E_DIR/tmp"
        echo "HOME=$E2E_DIR"
        echo "MEDIA_ROOT=$E2E_DIR/media"
        echo "PHONE_RECORDING_STORAGE_ROOT=$E2E_DIR/phone-recordings"
        echo "SESSION_REPLAY_STORAGE_ROOT=$E2E_DIR/session-replays"
        echo "E2E_STATE_DIR=$E2E_DIR"
        echo "DOCKETWORKS_ENV_FILE=$E2E_ENV"
        echo "PLAYWRIGHT_BROWSERS_PATH=$PLAYWRIGHT_BROWSERS_PATH"
        cat "$E2E_CREDENTIALS"
    } > "$E2E_ENV"
    chown -R "$INSTANCE_USER:$INSTANCE_USER" "$E2E_DIR"
    chmod 700 "$E2E_DIR"
    chmod 600 "$E2E_ENV"

    # Fence up, then the copy: anything a user did before this point is in
    # the live database, which is only read from here on.
    cat > "$FENCE" <<'FENCE_EOF'
# verify-instance.sh --e2e: the instance serves a copy of its database for the run (ADR 0064)
if ($remote_addr != 127.0.0.1) { return 503; }
FENCE_EOF
    nginx -t && systemctl reload nginx
    echo "E2E: copying $DB_NAME into $SCRUB_DB_NAME..."
    "$SCRIPT_DIR/dw-run.sh" "$INSTANCE" python manage.py scrub_copy load

    # The units onto the copy: a later EnvironmentFile= overrides the
    # instance .env (an Environment= line would not). Beat stays down for
    # the window — its hourly sync outlasts the teardown settle and its phone
    # and LLM tasks spend for nothing; no spec depends on it.
    for unit in "${RUNTIME_UNIT_NAMES[@]}"; do
        mkdir -p "/run/systemd/system/$unit-$INSTANCE.service.d"
        printf '[Service]\nEnvironmentFile=%s\n' "$E2E_ENV" > "/run/systemd/system/$unit-$INSTANCE.service.d/e2e.conf"
    done
    systemctl daemon-reload
    systemctl stop "celery-beat-$INSTANCE"
    systemctl restart "celery-worker-$INSTANCE" "gunicorn-$INSTANCE"
    wait_for_build_id || { echo "ERROR: $INSTANCE did not come up on the copy." >&2; exit 1; }

    in_window() { DW_ENV_FILE="$E2E_ENV" "$SCRIPT_DIR/dw-run.sh" "$INSTANCE" "$@"; }
    # run_e2e.sh's order: the shape report, the fixtures a production
    # database never held, the fake seeded from the copy, the reset that
    # clears any residue, then the suite.
    in_window python scripts/checks/data_shape_gap.py
    in_window python manage.py e2e_ensure_fixtures
    in_window python manage.py fake_xero_seed --replace
    in_window npm --prefix frontend run test:e2e:reset -- --confirm
    rm -rf "$E2E_DIR/test-results" "$E2E_DIR/playwright-report"
    echo "E2E: running the suite against https://$FQDN on a copy of $DB_NAME with the fake Xero..."
    in_window npm --prefix frontend run test:e2e -- "${PLAYWRIGHT_ARGS[@]}" || E2E_STATUS=$?

    e2e_restore_instance
    if (( E2E_STATUS == 0 )); then
        echo "E2E PASSED AGAINST FAKE XERO on a copy of $DB_NAME — deployment verification, not a merge gate."
    else
        echo "E2E FAILED (exit $E2E_STATUS) — report and traces under $E2E_DIR" >&2
    fi
    echo ""
fi

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
EXPECTED_SHA="$(instance_current_sha "$INSTANCE")"
BUILD_ID=""
wait_for_build_id || true
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
check --verbose "IntegrationSettings live connections" \
    "$SCRIPT_DIR/dw-run.sh" "$INSTANCE" \
    python -m scripts.ops.restore_checks.check_integration_settings

# Fable: every JobFile row's bytes must exist under DROPBOX_WORKFLOW_FOLDER.
# Process liveness cannot catch the failure class this guards: a root
# pointed one directory too high 404s every attachment while Dropbox
# sync, systemd and disk all report healthy (2026-08-31 production
# incident — the media probe above only proves MEDIA_ROOT).
check --verbose "JobFile attachments resolve on disk" \
    "$SCRIPT_DIR/dw-run.sh" "$INSTANCE" \
    python -m scripts.ops.restore_checks.check_jobfiles

# Opus: the instance's dropbox directory is the client's Maestral sync root,
# and an external writer (the office scanner) delivers into it through its
# membership of the instance group. A run of instance.sh that reset the mode
# to 700 cut delivery silently while Maestral, systemd and disk all
# reported healthy (KAN-360). The check above cannot see it: rows already on
# disk still resolve while nothing new can arrive.
dropbox_root_group_accessible() {
    local mode
    mode="$(stat -c %a "$INSTANCE_DIR/dropbox")"
    if [[ "$mode" != "2770" ]]; then
        echo "  $INSTANCE_DIR/dropbox is mode $mode, expected 2770" >&2
        return 1
    fi
}
check --verbose "dropbox sync root is group-accessible" dropbox_root_group_accessible

# --- Celery broker: this instance's Redis database is its alone ---
# v1 pins its broker to database 1 without naming it in its env, which is
# how the first v2 instance on this box once shared v1's broker and each
# worker consumed the other's tasks; 0 and 2 are the default and the shared
# cache. redis_db_of_env is the one reading the allocator uses too.
broker_db_isolated() {
    local mine other db
    mine="$(redis_db_of_env "$INSTANCE_DIR/.env")" || return 1
    case "$mine" in
        0|1|2)
            echo "  Redis database $mine is reserved (0 default, 1 v1 broker, 2 shared cache)" >&2
            return 1 ;;
    esac
    for other in "$INSTANCES_DIR"/*/.env; do
        [[ "$other" == "$INSTANCE_DIR/.env" ]] && continue
        db="$(redis_db_of_env "$other")" || return 1
        if [[ "$db" == "$mine" ]]; then
            echo "  $other also binds Redis database $mine" >&2
            return 1
        fi
    done
}
check --verbose "Celery broker Redis database is this instance's alone" broker_db_isolated

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
if (( E2E_STATUS != 0 )); then
    echo "Verification checks passed for $INSTANCE, but the E2E suite failed (exit $E2E_STATUS)."
    exit "$E2E_STATUS"
fi
echo "All verification checks passed for $INSTANCE."
