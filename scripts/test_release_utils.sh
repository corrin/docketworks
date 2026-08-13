#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=server/common.sh
source "$SCRIPT_DIR/server/common.sh"
# shellcheck source=server/release-utils.sh
source "$SCRIPT_DIR/server/release-utils.sh"

assert_eq() {
    local expected="$1"
    local actual="$2"
    local message="$3"

    if [[ "$actual" != "$expected" ]]; then
        echo "FAIL: $message" >&2
        echo "  expected: $expected" >&2
        echo "  actual:   $actual" >&2
        exit 1
    fi
}

assert_success() {
    local message="$1"
    shift

    if ! "$@"; then
        echo "FAIL: $message" >&2
        exit 1
    fi
}

assert_failure() {
    local message="$1"
    shift

    if "$@"; then
        echo "FAIL: $message" >&2
        exit 1
    fi
}

TMP_DIR="$(mktemp -d)"
cleanup() {
    rm -rf "$TMP_DIR"
}
trap cleanup EXIT

BASE_DIR="$TMP_DIR/opt/docketworks"
INSTANCES_DIR="$BASE_DIR/instances"
RELEASES_DIR="$BASE_DIR/releases"
mkdir -p "$INSTANCES_DIR/msm-uat" "$RELEASES_DIR"

FULL_SHA="71f21401aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
ROLLED_FROM_SHA="f1e8535bbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
OTHER_SHA="aaaaaaaa11111111111111111111111111111111"
RECENT_SHA="bbbbbbbb22222222222222222222222222222222"
mkdir -p \
    "$RELEASES_DIR/$FULL_SHA" \
    "$RELEASES_DIR/$ROLLED_FROM_SHA" \
    "$RELEASES_DIR/$OTHER_SHA" \
    "$RELEASES_DIR/$RECENT_SHA"
touch \
    "$RELEASES_DIR/$FULL_SHA/.complete" \
    "$RELEASES_DIR/$ROLLED_FROM_SHA/.complete" \
    "$RELEASES_DIR/$OTHER_SHA/.complete" \
    "$RELEASES_DIR/$RECENT_SHA/.complete"
printf "%s\n" "$FULL_SHA" > "$RELEASES_DIR/$FULL_SHA/.release-sha"
printf "%s\n" "$ROLLED_FROM_SHA" > "$RELEASES_DIR/$ROLLED_FROM_SHA/.release-sha"
printf "%s\n" "$OTHER_SHA" > "$RELEASES_DIR/$OTHER_SHA/.release-sha"
printf "%s\n" "$RECENT_SHA" > "$RELEASES_DIR/$RECENT_SHA/.release-sha"

assert_eq "71f21401" "$(short_release_sha "$FULL_SHA")" "short_release_sha returns 8 chars"

assert_failure \
    "latest-database rollback rejects the current release" \
    validate_rollback_target "msm-uat" "$FULL_SHA" "$FULL_SHA" "latest-db"

assert_success \
    "backup restoration accepts the current release for safety recovery" \
    validate_rollback_target "msm-uat" "$FULL_SHA" "$FULL_SHA" "restore-backup"

BACKUP_DIR="$TMP_DIR/backups"
mkdir -p "$BACKUP_DIR"
touch "$BACKUP_DIR/predeploy_20260626_010101_71f21401.sql.gz"
touch "$BACKUP_DIR/predeploy_20260626_020202_71f21401.sql.gz"
touch "$BACKUP_DIR/predeploy_20260626_030303_71f21402.sql.gz"

assert_eq \
    "$BACKUP_DIR/predeploy_20260626_020202_71f21401.sql.gz" \
    "$(newest_predeploy_backup_for_sha "$BACKUP_DIR" "71f21401")" \
    "newest_predeploy_backup_for_sha finds the newest exact 8-char backup suffix"

if newest_predeploy_backup_for_sha "$BACKUP_DIR" "71f2140" 2>/dev/null; then
    echo "FAIL: newest_predeploy_backup_for_sha rejects non-8-char hashes" >&2
    exit 1
fi

cat > "$INSTANCES_DIR/msm-uat/deploy-state.env" <<EOF
TRACKED_REF=origin/main
PREVIOUS_SHA=71f21401
CURRENT_SHA=f1e8535b
DEPLOYED_AT=2026-06-27T12:00:00+12:00
EOF

assert_eq \
    "origin/main" \
    "$(read_instance_deploy_ref "msm-uat")" \
    "read_instance_deploy_ref returns the instance's tracked ref"

mkdir -p "$INSTANCES_DIR/legacy-demo"
cat > "$INSTANCES_DIR/legacy-demo/deploy-state.env" <<EOF
PREVIOUS_SHA=71f21401
CURRENT_SHA=f1e8535b
DEPLOYED_AT=2026-06-27T12:00:00+12:00
EOF
assert_failure \
    "read_instance_deploy_ref rejects legacy state without a configured ref" \
    read_instance_deploy_ref "legacy-demo"

assert_success \
    "release_is_referenced treats 8-char deploy-state PREVIOUS_SHA as a release prefix" \
    release_is_referenced "$FULL_SHA"

assert_failure \
    "release_is_referenced does not match a different release" \
    release_is_referenced "$ROLLED_FROM_SHA"

assert_success \
    "state_sha_references_release accepts the canonical 8-char release prefix" \
    state_sha_references_release "71f21401" "$FULL_SHA"

assert_failure \
    "state_sha_references_release rejects old full-SHA deploy-state values" \
    state_sha_references_release "$FULL_SHA" "$FULL_SHA"

CHOWN_STUB_DIR="$TMP_DIR/stub-bin"
mkdir -p "$CHOWN_STUB_DIR"
printf '#!/bin/sh\nexit 0\n' > "$CHOWN_STUB_DIR/chown"
printf '#!/bin/sh\ncat\n' > "$CHOWN_STUB_DIR/tee"
# shellcheck disable=SC2016  # variables expand when the generated stub runs
printf '%s\n' \
    '#!/bin/sh' \
    'case "$1" in' \
    '    stop)' \
    '        [ "${SYSTEMCTL_FAIL_UNIT:-}" != "$2" ]' \
    '        ;;' \
    '    is-active)' \
    '        if [ "${SYSTEMCTL_ACTIVE_UNIT:-}" = "$2" ]; then' \
    '            echo active' \
    '            exit 0' \
    '        fi' \
    '        echo inactive' \
    '        exit 3' \
    '        ;;' \
    '    *) exit 2 ;;' \
    'esac' \
    > "$CHOWN_STUB_DIR/systemctl"
# shellcheck disable=SC2016  # positional parameters belong to the generated stub
printf '%s\n' \
    '#!/bin/sh' \
    '[ "$1" = "-u" ] || exit 2' \
    'shift 2' \
    'exec "$@"' \
    > "$CHOWN_STUB_DIR/sudo"
chmod +x "$CHOWN_STUB_DIR/chown"
chmod +x "$CHOWN_STUB_DIR/tee"
chmod +x "$CHOWN_STUB_DIR/systemctl"
chmod +x "$CHOWN_STUB_DIR/sudo"

PATH="$CHOWN_STUB_DIR:$PATH" assert_success \
    "strict service shutdown accepts inactive services" \
    stop_instance_services_strict "msm-uat"

export SYSTEMCTL_ACTIVE_UNIT="gunicorn-msm-uat"
PATH="$CHOWN_STUB_DIR:$PATH" assert_failure \
    "strict service shutdown rejects a service that remains active" \
    stop_instance_services_strict "msm-uat"
unset SYSTEMCTL_ACTIVE_UNIT

export SYSTEMCTL_FAIL_UNIT="celery-worker-msm-uat"
PATH="$CHOWN_STUB_DIR:$PATH" assert_failure \
    "strict service shutdown reports a failed stop" \
    stop_instance_services_strict "msm-uat"
unset SYSTEMCTL_FAIL_UNIT

printf 'DB_NAME=dw_msm_uat\n' > "$INSTANCES_DIR/msm-uat/.env"
mkdir -p "$RELEASES_DIR/$FULL_SHA/.venv/bin"
printf 'return 1\n' > "$RELEASES_DIR/$FULL_SHA/.venv/bin/activate"
COMMAND_MARKER="$TMP_DIR/release-command-ran"
PATH="$CHOWN_STUB_DIR:$PATH" assert_failure \
    "release commands stop when virtualenv activation fails" \
    run_release_command \
    "msm-uat" "$FULL_SHA" "dw_msm_uat" touch "$COMMAND_MARKER"
if [[ -e "$COMMAND_MARKER" ]]; then
    echo "FAIL: release command ran after virtualenv activation failed" >&2
    exit 1
fi

PATH="$CHOWN_STUB_DIR:$PATH" write_deploy_state \
    "msm-uat" \
    "$FULL_SHA" \
    "$ROLLED_FROM_SHA" \
    "$(id -un)" \
    "origin/production" \
    "deploy"

assert_eq \
    "TRACKED_REF=origin/production" \
    "$(sed -n '1p' "$INSTANCES_DIR/msm-uat/deploy-state.env")" \
    "write_deploy_state persists the tracked ref"

assert_eq \
    "PREVIOUS_SHA=71f21401" \
    "$(sed -n '2p' "$INSTANCES_DIR/msm-uat/deploy-state.env")" \
    "write_deploy_state persists an 8-char previous SHA"

assert_eq \
    "CURRENT_SHA=f1e8535b" \
    "$(sed -n '3p' "$INSTANCES_DIR/msm-uat/deploy-state.env")" \
    "write_deploy_state persists an 8-char current SHA"

assert_eq \
    "3" \
    "$(wc -l < "$INSTANCES_DIR/msm-uat/deploy-history.tsv")" \
    "write_deploy_state records the baseline and successful deployment"

assert_eq \
    $'deploy\t71f21401\tf1e8535b\torigin/production' \
    "$(tail -n 1 "$INSTANCES_DIR/msm-uat/deploy-history.tsv" | cut -f2-)" \
    "deployment history records the action, SHAs, and tracked ref"

HISTORY_OUTPUT="$(print_deploy_history "msm-uat")"
assert_eq \
    "COMPLETED AT" \
    "$(printf '%s\n' "$HISTORY_OUTPUT" | sed -n '1p' | cut -c1-12)" \
    "deployment history prints an operator-facing header"
assert_eq \
    "2" \
    "$(printf '%s\n' "$HISTORY_OUTPUT" | grep -c -- ' -> ')" \
    "deployment history prints each recorded transition"

assert_success \
    "release_is_referenced uses the canonical 8-char deploy-state PREVIOUS_SHA" \
    release_is_referenced "$FULL_SHA"

ln -sfn "../../releases/$FULL_SHA" "$INSTANCES_DIR/msm-uat/current"
ensure_instance_app_link "msm-uat"
assert_eq \
    "$(readlink -f "$INSTANCES_DIR/msm-uat/current")" \
    "$(readlink -f "$INSTANCES_DIR/msm-uat/app")" \
    "ensure_instance_app_link migrates current-only instances to app"

ensure_instance_app_link "msm-uat"
assert_eq \
    "$(readlink -f "$INSTANCES_DIR/msm-uat/current")" \
    "$(readlink -f "$INSTANCES_DIR/msm-uat/app")" \
    "ensure_instance_app_link tolerates matching app and current links"

mv "$INSTANCES_DIR/msm-uat/deploy-state.env" "$INSTANCES_DIR/msm-uat/deploy-state.env.testbak"
assert_success \
    "release_is_referenced uses the app symlink" \
    release_is_referenced "$FULL_SHA"
mv "$INSTANCES_DIR/msm-uat/deploy-state.env.testbak" "$INSTANCES_DIR/msm-uat/deploy-state.env"

remove_legacy_current_link "msm-uat"
if [[ -e "$INSTANCES_DIR/msm-uat/current" ]]; then
    echo "FAIL: remove_legacy_current_link removes matching legacy current link" >&2
    exit 1
fi
assert_eq \
    "$(release_path "$FULL_SHA")" \
    "$(readlink -f "$INSTANCES_DIR/msm-uat/app")" \
    "remove_legacy_current_link leaves app link in place"

ensure_instance_app_link "msm-uat"
assert_eq \
    "$(release_path "$FULL_SHA")" \
    "$(readlink -f "$INSTANCES_DIR/msm-uat/app")" \
    "ensure_instance_app_link leaves app-only instances unchanged"

ln -sfn "../../releases/$OTHER_SHA" "$INSTANCES_DIR/msm-uat/current"
if ensure_instance_app_link "msm-uat" 2>/dev/null; then
    echo "FAIL: ensure_instance_app_link rejects divergent app and current links" >&2
    exit 1
fi
rm -f "$INSTANCES_DIR/msm-uat/current"

touch -d "15 days ago" "$RELEASES_DIR/$ROLLED_FROM_SHA/.complete"
switch_instance_release "msm-uat" "$ROLLED_FROM_SHA"
if [[ -z "$(find "$RELEASES_DIR/$ROLLED_FROM_SHA/.complete" -mmin -2 -print)" ]]; then
    echo "FAIL: switch_instance_release refreshes the release last-used timestamp" >&2
    exit 1
fi

touch -d "15 days ago" "$RELEASES_DIR/$OTHER_SHA/.complete"
PATH="$CHOWN_STUB_DIR:$PATH" cleanup_unreferenced_releases ""
if [[ -d "$RELEASES_DIR/$OTHER_SHA" ]]; then
    echo "FAIL: cleanup removes an unreferenced release unused for 14 days" >&2
    exit 1
fi

if [[ ! -d "$RELEASES_DIR/$ROLLED_FROM_SHA" ]]; then
    echo "FAIL: cleanup retains a recently used release" >&2
    exit 1
fi

if [[ ! -d "$RELEASES_DIR/$RECENT_SHA" ]]; then
    echo "FAIL: cleanup retains a recent unreferenced release for 14 days" >&2
    exit 1
fi

echo "release-utils tests passed"
