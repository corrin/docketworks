#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/server/common.sh"
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

assert_eq "71f21401" "$(short_release_sha "$FULL_SHA")" "short_release_sha returns 8 chars"

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
PREVIOUS_SHA=71f21401
CURRENT_SHA=f1e8535b
DEPLOYED_AT=2026-06-27T12:00:00+12:00
EOF

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

write_deploy_state "msm-uat" "$FULL_SHA" "$ROLLED_FROM_SHA" "$(id -un)"

assert_eq \
    "PREVIOUS_SHA=71f21401" \
    "$(sed -n '1p' "$INSTANCES_DIR/msm-uat/deploy-state.env")" \
    "write_deploy_state persists an 8-char previous SHA"

assert_eq \
    "CURRENT_SHA=f1e8535b" \
    "$(sed -n '2p' "$INSTANCES_DIR/msm-uat/deploy-state.env")" \
    "write_deploy_state persists an 8-char current SHA"

assert_success \
    "release_is_referenced uses the canonical 8-char deploy-state PREVIOUS_SHA" \
    release_is_referenced "$FULL_SHA"

echo "release-utils tests passed"
