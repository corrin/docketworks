#!/bin/bash
set -euo pipefail

# Static checks for the server suite: every script parses and passes
# ShellCheck, rendered templates carry the v2 contract (uvicorn serving
# model, config module names, scoped /media/ alias, auth rate limits),
# the env template stays in sync with .env.example, and the fail2ban
# filters match exactly the lines they should and nothing else.
# Runs anywhere (no root, no services); wired into the cheap gate tier.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
TEMPLATE_DIR="$SCRIPT_DIR/templates"

FAILURES=0
fail() {
    echo "FAIL: $*" >&2
    FAILURES=$((FAILURES + 1))
}

# --- Every shipped script parses and is ShellCheck-clean ---
if ! command -v shellcheck >/dev/null; then
    echo "ERROR: shellcheck is required (apt install shellcheck)." >&2
    exit 1
fi
SCRIPTS=(
    "$SCRIPT_DIR"/*.sh
    "$SCRIPT_DIR"/cutover/*.sh
    "$REPO_ROOT"/scripts/backup_db.sh
    "$REPO_ROOT"/scripts/backup_instance_files.sh
    "$REPO_ROOT"/scripts/predeploy_backup.sh
    "$REPO_ROOT"/scripts/rollback.sh
    "$REPO_ROOT"/scripts/cleanup_backups.sh
    "$REPO_ROOT"/scripts/test_release_utils.sh
    "$REPO_ROOT"/scripts/ops/*.sh
)
for script in "${SCRIPTS[@]}"; do
    bash -n "$script" || fail "bash -n $script"
done
shellcheck -x -P SCRIPTDIR "${SCRIPTS[@]}" || fail "shellcheck"

render() {
    local template="$1"
    sed \
        -e "s|__INSTANCE__|test-uat|g" \
        -e "s|__INSTANCE_USER__|dw_test_uat|g" \
        -e "s|__FQDN__|test-uat.docketworks.site|g" \
        -e "s|__CERT_DOMAIN__|docketworks.site|g" \
        -e "s|__DB_NAME__|dw_test_uat|g" \
        -e "s|__DB_USER__|dw_test_uat|g" \
        -e "s|__DB_PASSWORD__|pw|g" \
        -e "s|__SCRUB_DB_NAME__|dw_test_uat_scrub|g" \
        -e "s|__TEST_DB_USER__|dw_test_uat_test|g" \
        -e "s|__TEST_DB_PASSWORD__|tpw|g" \
        -e "s|__SECRET_KEY__|sk|g" \
        -e "s|__JWT_SIGNING_KEY__|jwtk|g" \
        -e "s|__REDIS_DB__|3|g" \
        -e "s|__RCLONE_CONFIG__|/opt/docketworks/config/rclone/test-uat.conf|g" \
        "$template"
}

assert_no_tokens() {
    local name="$1"
    local rendered="$2"
    if grep -q '__[A-Z0-9_]*__' <<<"$rendered"; then
        fail "$name: unresolved __TOKEN__ after full substitution: $(grep -o '__[A-Z0-9_]*__' <<<"$rendered" | sort -u | tr '\n' ' ')"
    fi
}

# --- nginx: scoped media alias, rate limits, no v1 leftovers ---
NGINX="$(render "$TEMPLATE_DIR/nginx-instance.conf.template")"
assert_no_tokens "nginx" "$NGINX"
grep -q 'alias /opt/docketworks/instances/test-uat/mediafiles/;' <<<"$NGINX" \
    || fail "nginx: /media/ must alias exactly the instance mediafiles dir"
if grep -E 'alias .*(dropbox|phone-recordings)' <<<"$NGINX" >/dev/null; then
    fail "nginx: authenticated file roots must never be aliased"
fi
grep -q 'limit_req zone=dw_login burst=5 nodelay;' <<<"$NGINX" \
    || fail "nginx: login rate limit missing"
grep -q 'limit_req zone=dw_refresh burst=20 nodelay;' <<<"$NGINX" \
    || fail "nginx: refresh rate limit missing"
grep -q 'location = /api/accounts/token/ {' <<<"$NGINX" \
    || fail "nginx: exact-match login location missing"
grep -q 'location = /api/accounts/token/refresh/ {' <<<"$NGINX" \
    || fail "nginx: exact-match refresh location missing"
grep -q 'zone=dw_login' "$TEMPLATE_DIR/nginx-ratelimit.conf" \
    || fail "ratelimit conf: dw_login zone missing"
grep -q 'limit_req_status 429;' "$TEMPLATE_DIR/nginx-ratelimit.conf" \
    || fail "ratelimit conf: 429 status missing"
# The stream's settings are asserted INSIDE its own location and their absence
# INSIDE /api/: a substring check over the whole file passes just as well when
# the hour-long timeouts sit on every API request, which is the arrangement
# this pair of checks exists to reject.
location_block() {
    local opening="$1"
    awk -v opening="$opening" '
        index($0, opening) { inside = 1 }
        inside { print }
        inside && /^    }$/ { exit }
    ' <<<"$NGINX"
}

SSE_BLOCK="$(location_block 'location = /api/data-versions/stream/ {')"
API_BLOCK="$(location_block 'location /api/ {')"
[[ -n "$SSE_BLOCK" ]] || fail "nginx: exact-match /api/data-versions/stream/ location missing"
[[ -n "$API_BLOCK" ]] || fail "nginx: /api/ location missing"

SSE_SETTINGS=(
    'proxy_buffering off;'
    'proxy_read_timeout 1h;'
    'proxy_send_timeout 1h;'
    'proxy_http_version 1.1;'
    'proxy_set_header Connection "";'
)
for setting in "${SSE_SETTINGS[@]}"; do
    grep -qF "$setting" <<<"$SSE_BLOCK" \
        || fail "nginx: '$setting' missing from the SSE stream location (the stream needs it)"
    if grep -qF "$setting" <<<"$API_BLOCK"; then
        fail "nginx: '$setting' must not apply to ordinary API requests"
    fi
done
grep -q 'proxy_pass http://unix:/opt/docketworks/instances/test-uat/gunicorn.sock;' <<<"$SSE_BLOCK" \
    || fail "nginx: SSE stream location must proxy to the instance socket"
# Escaped rather than single-quoted: these are nginx variables, and shellcheck
# reads a single-quoted $name as a shell expansion someone forgot to expand.
FORWARDED_HEADERS=(
    "proxy_set_header Host \$host;"
    "proxy_set_header X-Real-IP \$remote_addr;"
    "proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;"
    "proxy_set_header X-Forwarded-Proto \$scheme;"
)
for header in "${FORWARDED_HEADERS[@]}"; do
    grep -qF "$header" <<<"$SSE_BLOCK" \
        || fail "nginx: SSE stream location must set '$header' like /api/ does"
done

# --- systemd units: v2 serving model and module names ---
GUNICORN="$(render "$TEMPLATE_DIR/gunicorn-instance.service.template")"
assert_no_tokens "gunicorn unit" "$GUNICORN"
grep -q -- '-k uvicorn_worker.UvicornWorker' <<<"$GUNICORN" || fail "gunicorn: uvicorn worker class required"
grep -q -- '--workers 4' <<<"$GUNICORN" || fail "gunicorn: 4 workers required"
grep -q -- '--timeout 180' <<<"$GUNICORN" || fail "gunicorn: 180s worker timeout required"
grep -q 'config.asgi:application' <<<"$GUNICORN" || fail "gunicorn: must serve config.asgi"
if grep -q 'docketworks.wsgi' <<<"$GUNICORN"; then fail "gunicorn: v1 wsgi module leaked"; fi
if grep -q 'config.wsgi' <<<"$GUNICORN"; then fail "gunicorn: wsgi module leaked, must serve config.asgi"; fi

BEAT="$(render "$TEMPLATE_DIR/celery-beat-instance.service.template")"
assert_no_tokens "celery-beat unit" "$BEAT"
grep -q -- '-A config beat' <<<"$BEAT" || fail "celery-beat: must target -A config"
if grep -q 'DatabaseScheduler' <<<"$BEAT"; then
    fail "celery-beat: DatabaseScheduler leaked (v2 schedules in code)"
fi
# Without --schedule, PersistentScheduler writes its shelve file to CWD —
# the app symlink into the immutable release dir — and beat crash-loops on
# permission denied (msm-uat, NRestarts>1900). The file must live in the
# instance root, the writable dir the instance user owns.
grep -q -- '--schedule=/opt/docketworks/instances/test-uat/celerybeat-schedule' <<<"$BEAT" \
    || fail "celery-beat: --schedule must point at the instance root, not default to the immutable release CWD"

WORKER="$(render "$TEMPLATE_DIR/celery-worker-instance.service.template")"
assert_no_tokens "celery-worker unit" "$WORKER"
grep -q -- '-A config worker' <<<"$WORKER" || fail "celery-worker: must target -A config"

# --- env template: full render, and in sync with .env.example ---
ENV_RENDERED="$(render "$TEMPLATE_DIR/env-instance.template")"
assert_no_tokens "env" "$ENV_RENDERED"
while IFS='=' read -r var _; do
    [[ "$var" =~ ^[A-Z][A-Z0-9_]*$ ]] || continue
    grep -q "^$var=" <<<"$ENV_RENDERED" \
        || fail "env template: $var is in .env.example but not in env-instance.template"
done < "$REPO_ROOT/.env.example"

# --- JSON fixture templates: a rendered fixture must parse, or loaddata is the first to know ---
for json_template in ai-providers xero-apps integration-settings; do
    JSON_RENDERED="$(render "$TEMPLATE_DIR/$json_template.json.template" \
        | sed -e 's/__[A-Z_]*_JSON__/"sample"/g' -e 's/__[A-Z_]*_ENABLED__/false/g' -e 's/__[A-Z_]*__/sample/g')"
    python3 -m json.tool <<<"$JSON_RENDERED" >/dev/null \
        || fail "$json_template.json.template: does not render to valid JSON"
done

# --- fail2ban filters: 401s on the exact routes match; nothing else does ---
check_filter() {
    local filter_file="$1"
    shift
    python3 - "$filter_file" "$@" <<'PYEOF'
import re
import sys

filter_file = sys.argv[1]
cases = sys.argv[2:]  # alternating expectation ("match"/"nomatch") and log line

failregex = None
with open(filter_file) as f:
    for line in f:
        if line.startswith("failregex"):
            failregex = line.split("=", 1)[1].strip()
if failregex is None:
    raise SystemExit(f"{filter_file}: no failregex found")

# fail2ban substitutes <HOST> with its host-matching group.
pattern = re.compile(failregex.replace("<HOST>", r"(?P<host>\S+)"))

failures = 0
for expectation, line in zip(cases[0::2], cases[1::2], strict=True):
    matched = pattern.search(line) is not None
    expected = expectation == "match"
    if matched != expected:
        print(f"FAIL: {filter_file}: expected {expectation} for: {line}", file=sys.stderr)
        failures += 1
sys.exit(1 if failures else 0)
PYEOF
}

TS='[12/Aug/2026:22:10:01 +1200]'
TAIL='52 "-" "Mozilla" rt=0.012 uct=0.001 uht=0.010 urt=0.010'
LOGIN_FILTER="$TEMPLATE_DIR/fail2ban-filter-docketworks-auth-login.conf"
REFRESH_FILTER="$TEMPLATE_DIR/fail2ban-filter-docketworks-auth-refresh.conf"

check_filter "$LOGIN_FILTER" \
    match   "203.0.113.9 - - $TS \"POST /api/accounts/token/ HTTP/1.1\" 401 $TAIL" \
    match   "203.0.113.9 - - $TS \"POST /api/accounts/token/?evade=1 HTTP/1.1\" 401 $TAIL" \
    match   "2001:db8::7 - - $TS \"POST /api/accounts/token/ HTTP/2.0\" 401 $TAIL" \
    nomatch "203.0.113.9 - - $TS \"POST /api/accounts/token/ HTTP/1.1\" 200 $TAIL" \
    nomatch "203.0.113.9 - - $TS \"POST /api/accounts/token/ HTTP/1.1\" 429 $TAIL" \
    nomatch "203.0.113.9 - - $TS \"POST /api/accounts/token/refresh/ HTTP/1.1\" 401 $TAIL" \
    nomatch "203.0.113.9 - - $TS \"GET /api/accounts/token/ HTTP/1.1\" 401 $TAIL" \
    nomatch "203.0.113.9 - - $TS \"POST /api/jobs/ HTTP/1.1\" 401 $TAIL" \
    nomatch "203.0.113.9 - - $TS \"POST /api/accounts/token/ HTTP/1.1\" 4011 $TAIL" \
    || fail "login fail2ban filter regex"

check_filter "$REFRESH_FILTER" \
    match   "203.0.113.9 - - $TS \"POST /api/accounts/token/refresh/ HTTP/1.1\" 401 $TAIL" \
    match   "203.0.113.9 - - $TS \"POST /api/accounts/token/refresh/?evade=1 HTTP/1.1\" 401 $TAIL" \
    nomatch "203.0.113.9 - - $TS \"POST /api/accounts/token/refresh/ HTTP/1.1\" 200 $TAIL" \
    nomatch "203.0.113.9 - - $TS \"POST /api/accounts/token/refresh/ HTTP/1.1\" 429 $TAIL" \
    nomatch "203.0.113.9 - - $TS \"POST /api/accounts/token/ HTTP/1.1\" 401 $TAIL" \
    || fail "refresh fail2ban filter regex"

# When the real tool is installed (as it is on servers), prove the filter
# files parse and match through fail2ban itself, not just through re.
if command -v fail2ban-regex >/dev/null; then
    SAMPLE="$(mktemp)"
    trap 'rm -f "$SAMPLE"' EXIT
    echo "203.0.113.9 - - $TS \"POST /api/accounts/token/ HTTP/1.1\" 401 $TAIL" > "$SAMPLE"
    fail2ban-regex --print-no-missed "$SAMPLE" "$LOGIN_FILTER" | grep -q 'Matched: 1' \
        || fail "fail2ban-regex: login filter did not match its sample"
fi

# --- jail template sanity ---
JAIL="$TEMPLATE_DIR/fail2ban-jail-docketworks.conf"
grep -q '^banaction = ufw' "$JAIL" || fail "jail: UFW must be the ban action"
grep -q 'docketworks_\*_access.log' "$JAIL" || fail "jail: per-instance access-log glob missing"

# --- company-defaults label rewrite: v1 spelling becomes v2's, once ---
LABEL_TMP="$(mktemp)"
LABEL_OUT="$(
    # shellcheck source=common.sh
    # Sourced scripts reassign SCRIPT_DIR inside this subshell only; the
    # outer value is untouched by construction.
    # shellcheck disable=SC2031
    source "$SCRIPT_DIR/common.sh"
    printf '[{"model": "workflow.companydefaults"}, {"model": "company.company"}]' > "$LABEL_TMP"
    rewrite_v1_company_defaults_labels "$LABEL_TMP" && echo "REWROTE"
    rewrite_v1_company_defaults_labels "$LABEL_TMP" || echo "SECOND_RUN_NOOP"
    cat "$LABEL_TMP"
)"
echo "$LABEL_OUT" | grep -q "REWROTE" || fail "label rewrite: did not report rewriting a v1 file"
echo "$LABEL_OUT" | grep -q "SECOND_RUN_NOOP" || fail "label rewrite: not idempotent"
echo "$LABEL_OUT" | grep -q '"core.companydefaults"' || fail "label rewrite: v2 label missing after rewrite"
echo "$LABEL_OUT" | grep -q '"workflow.companydefaults"' && fail "label rewrite: v1 label survived"
rm -f "$LABEL_TMP"

# --- instance credentials: Maps is required before any instance mutation ---
CREDENTIAL_TMP="$(mktemp -d)"
CREDENTIAL_FILE="$CREDENTIAL_TMP/test-uat.credentials.env"
GCP_TEST_KEY="$CREDENTIAL_TMP/gcp.json"
touch "$GCP_TEST_KEY"
printf '%s\n' \
    "GCP_CREDENTIALS=$GCP_TEST_KEY" \
    "BACKUP_GDRIVE_TEAM_DRIVE_ID=drive" \
    "ANTHROPIC_API_KEY=anthropic" \
    "GEMINI_API_KEY=gemini" \
    "MISTRAL_API_KEY=mistral" \
    "XERO_CLIENT_ID=client" \
    "XERO_CLIENT_SECRET=secret" \
    "XERO_WEBHOOK_KEY=webhook" \
    "XERO_REDIRECT_URI=https://test-uat.docketworks.site/api/xero/oauth/callback/" \
    "GOOGLE_MAPS_API_KEY=" \
    "PHONE_PROVIDER_ENABLED=false" \
    "PHONE_PROVIDER_RECORDING_DELETION_ENABLED=false" \
    > "$CREDENTIAL_FILE"
CREDENTIAL_OUT="$CREDENTIAL_TMP/output"
if (
    # shellcheck source=instance.sh
    # Sourced scripts reassign SCRIPT_DIR inside this subshell only; the
    # outer value is untouched by construction.
    # shellcheck disable=SC2031
    source "$SCRIPT_DIR/instance.sh"
    require_root_owned_credentials_file() { :; }
    require_instance_credentials "$CREDENTIAL_FILE"
) > "$CREDENTIAL_OUT" 2>&1; then
    fail "credentials: accepted a blank GOOGLE_MAPS_API_KEY"
fi
grep -q 'GOOGLE_MAPS_API_KEY' "$CREDENTIAL_OUT" \
    || fail "credentials: refusal did not name GOOGLE_MAPS_API_KEY"
sed -i 's/^GOOGLE_MAPS_API_KEY=$/GOOGLE_MAPS_API_KEY=maps-key/' "$CREDENTIAL_FILE"
if ! (
    # shellcheck source=instance.sh
    # Sourced scripts reassign SCRIPT_DIR inside this subshell only; the
    # outer value is untouched by construction.
    # shellcheck disable=SC2031
    source "$SCRIPT_DIR/instance.sh"
    require_root_owned_credentials_file() { :; }
    require_instance_credentials "$CREDENTIAL_FILE"
) > "$CREDENTIAL_OUT" 2>&1; then
    fail "credentials: refused a complete credentials file with a Maps key"
fi
rm -rf "$CREDENTIAL_TMP"

# The verifier's service checks must catch a crash loop: with
# Restart=always a crash-looping unit is "active" for a slice of every
# RestartSec cycle, so a bare is-active check verified UAT's broken beat
# green. Pin the NRestarts-stability probe and its use for all three
# runtime units.
# SCRIPT_DIR's subshell reassignments never reach this scope.
# shellcheck disable=SC2031
grep -q 'NRestarts' "$SCRIPT_DIR/verify-instance.sh" \
    || fail "verify-instance: service checks must assert NRestarts stability, not bare is-active"
for unit in gunicorn celery-worker celery-beat; do
    # shellcheck disable=SC2031
    grep -qF "unit_running_stably \"$unit-\$INSTANCE\"" "$SCRIPT_DIR/verify-instance.sh" \
        || fail "verify-instance: $unit check must use the crash-loop-aware stability probe"
done

# The permanent verifier's final success must include the real DB-backed
# integration probe; a standalone restore check cannot make that claim true.
# Anchored on the live invocation (uncommented `check`, dw-run, module path
# across its continuation lines), so commenting the block out while
# debugging cannot leave this gate green.
# The $-signs are literal pattern text; SCRIPT_DIR's subshell reassignments
# never reach this scope.
# shellcheck disable=SC2016,SC2031
grep -Pzoq '(?m)^check --verbose "IntegrationSettings live connections" \\\n\s*"\$SCRIPT_DIR/dw-run\.sh" "\$INSTANCE" \\\n\s*python -m scripts\.ops\.restore_checks\.check_integration_settings' \
    "$SCRIPT_DIR/verify-instance.sh" \
    || fail "verify-instance: live IntegrationSettings probe invocation missing or disabled"

# --- rclone config writer: a bare service account is refused ---
# A service account without a shared drive has zero quota, so that config
# uploads nothing — prod ran it red every night. chown/chmod are shadowed
# so the happy path runs without root.
RCLONE_TMP="$(mktemp -d)"
RCLONE_OUT="$(
    # Subshell so common.sh's vars and the shadowing stay contained.
    set +e
    # shellcheck source=common.sh
    # shellcheck disable=SC2031
    source "$SCRIPT_DIR/common.sh"
    RCLONE_CONFIG_DIR="$RCLONE_TMP"
    chown() { :; }
    chmod() { :; }
    if write_instance_rclone_config "test-uat" "dw_test_uat" "" "" 2>&1; then
        echo "UNEXPECTED_SUCCESS"
    fi
    write_instance_rclone_config "test-uat" "dw_test_uat" "folder123" "drive456" 2>&1
)"
echo "$RCLONE_OUT" | grep -q "UNEXPECTED_SUCCESS" \
    && fail "rclone writer: accepted a config with no shared drive"
echo "$RCLONE_OUT" | grep -q "BACKUP_GDRIVE_TEAM_DRIVE_ID" \
    || fail "rclone writer: refusal must name the missing value"
RENDERED_RCLONE="$RCLONE_TMP/test-uat.conf"
grep -q '^team_drive = drive456$' "$RENDERED_RCLONE" \
    || fail "rclone writer: team_drive missing from rendered config"
grep -q '^root_folder_id = folder123$' "$RENDERED_RCLONE" \
    || fail "rclone writer: root_folder_id missing from rendered config"
rm -rf "$RCLONE_TMP"

if (( FAILURES > 0 )); then
    echo "$FAILURES server template check(s) failed." >&2
    exit 1
fi
echo "server template checks passed"
