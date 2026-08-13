#!/bin/bash
set -euo pipefail

# Static checks for the server suite: every script parses and passes
# ShellCheck, rendered templates carry the v2 contract (gthread serving
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

# --- systemd units: v2 serving model and module names ---
GUNICORN="$(render "$TEMPLATE_DIR/gunicorn-instance.service.template")"
assert_no_tokens "gunicorn unit" "$GUNICORN"
grep -q -- '--worker-class gthread' <<<"$GUNICORN" || fail "gunicorn: gthread worker class required"
grep -q -- '--threads 16' <<<"$GUNICORN" || fail "gunicorn: 16 threads required"
grep -q 'config.wsgi:application' <<<"$GUNICORN" || fail "gunicorn: must serve config.wsgi"
if grep -q 'docketworks.wsgi' <<<"$GUNICORN"; then fail "gunicorn: v1 wsgi module leaked"; fi

BEAT="$(render "$TEMPLATE_DIR/celery-beat-instance.service.template")"
assert_no_tokens "celery-beat unit" "$BEAT"
grep -q -- '-A config beat' <<<"$BEAT" || fail "celery-beat: must target -A config"
if grep -q 'DatabaseScheduler' <<<"$BEAT"; then
    fail "celery-beat: DatabaseScheduler leaked (v2 schedules in code)"
fi

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

if (( FAILURES > 0 )); then
    echo "$FAILURES server template check(s) failed." >&2
    exit 1
fi
echo "server template checks passed"
