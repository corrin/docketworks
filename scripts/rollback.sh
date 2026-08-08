#!/bin/bash
set -euo pipefail

# Roll an instance back to an earlier release. The default keeps the latest
# database and runs Django reverse migrations. --restore-backup restores the
# database snapshot captured before the target release was replaced.
#
# Usage: rollback.sh <instance> <8-char-sha> [--latest-db|--restore-backup]

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/server/common.sh"
source "$SCRIPT_DIR/server/release-utils.sh"

if [[ $EUID -ne 0 ]]; then
    echo "ERROR: This script must be run as root (use sudo)." >&2
    exit 1
fi

USAGE="Usage: $0 <instance> <8-char-sha> [--latest-db|--restore-backup]"
if ! parsed=$(getopt -o '' --long latest-db,restore-backup -n "$(basename "$0")" -- "$@"); then
    echo "$USAGE" >&2
    exit 1
fi
eval set -- "$parsed"

MODE="latest-db"
MODE_SET=false
while true; do
    case "$1" in
        --latest-db)
            if [[ "$MODE_SET" == "true" ]]; then
                echo "ERROR: Choose only one rollback mode." >&2
                exit 1
            fi
            MODE="latest-db"
            MODE_SET=true
            shift
            ;;
        --restore-backup)
            if [[ "$MODE_SET" == "true" ]]; then
                echo "ERROR: Choose only one rollback mode." >&2
                exit 1
            fi
            MODE="restore-backup"
            MODE_SET=true
            shift
            ;;
        --) shift; break ;;
    esac
done

if [[ $# -ne 2 ]]; then
    echo "$USAGE" >&2
    exit 1
fi

INSTANCE="$1"
HASH="$2"
INSTANCE_DIR="$INSTANCES_DIR/$INSTANCE"
ENV_FILE="$INSTANCE_DIR/.env"
BACKUP_DIR="$INSTANCE_DIR/backups"
INST_USER="$(instance_user "$INSTANCE")"

if [[ ! -f "$ENV_FILE" ]]; then
    echo "ERROR: $ENV_FILE missing" >&2
    exit 1
fi

DB_NAME="$(read_env_value "$ENV_FILE" DB_NAME)"
DB_USER="$(read_env_value "$ENV_FILE" DB_USER)"
if [[ -z "$DB_NAME" || -z "$DB_USER" ]]; then
    echo "ERROR: DB_NAME and DB_USER must be set in $ENV_FILE" >&2
    exit 1
fi

exec 9>"$BASE_DIR/.deploy.lock"
if ! flock -n 9; then
    echo "ERROR: another deploy or rollback is already running." >&2
    exit 1
fi

CURRENT_SHA="$(instance_current_sha "$INSTANCE")"
if [[ -z "$CURRENT_SHA" ]]; then
    echo "ERROR: could not determine the current release for $INSTANCE" >&2
    exit 1
fi

TARGET_SHA="$(resolve_existing_release_sha "$HASH")"
ensure_release "$TARGET_SHA"
validate_rollback_target "$INSTANCE" "$CURRENT_SHA" "$TARGET_SHA" "$MODE"

TRACKED_REF="$(read_instance_deploy_ref "$INSTANCE")"
TARGET_SHORT="$(short_release_sha "$TARGET_SHA")"
CURRENT_SHORT="$(short_release_sha "$CURRENT_SHA")"
TARGETS_FILE="$(mktemp)"
RESTORE_DB=""

cleanup() {
    local command_status=$?
    local cleanup_status=0
    trap - EXIT
    set +e

    if ! rm -f "$TARGETS_FILE"; then
        echo "ERROR: failed to remove temporary migration targets file $TARGETS_FILE." >&2
        cleanup_status=1
    fi
    if [[ -n "$RESTORE_DB" ]]; then
        if ! sudo -u postgres dropdb --if-exists "$RESTORE_DB"; then
            echo "ERROR: failed to remove temporary restore database $RESTORE_DB." >&2
            cleanup_status=1
        fi
    fi

    if [[ $command_status -ne 0 ]]; then
        exit "$command_status"
    fi
    exit "$cleanup_status"
}
trap cleanup EXIT

start_services() {
    if [[ -f "$INSTANCE_DIR/.dr-mode" ]]; then
        echo "DR mode present; leaving services stopped."
        return 0
    fi
    systemctl start "celery-worker-$INSTANCE"
    systemctl start "celery-beat-$INSTANCE"
    systemctl start "gunicorn-$INSTANCE"
}

take_safety_backup() {
    "$SCRIPT_DIR/predeploy_backup.sh" "$INSTANCE"
    SAFETY_BACKUP="$(newest_predeploy_backup_for_sha "$BACKUP_DIR" "$CURRENT_SHORT")"
    echo "Current database safety backup: $SAFETY_BACKUP"
}

confirm_rollback() {
    echo
    echo "Instance:    $INSTANCE"
    echo "Current:     $CURRENT_SHORT"
    echo "Target:      $TARGET_SHORT"
    echo "Tracked ref: $TRACKED_REF"
    echo "Mode:        $MODE"
    echo
    echo "Recent deployment history:"
    print_deploy_history "$INSTANCE" | tail -n 12
    echo
    read -rp "Continue with this rollback? [y/N] " answer
    if [[ "$answer" != "y" && "$answer" != "Y" ]]; then
        echo "Aborted."
        exit 1
    fi
}

if [[ "$MODE" == "latest-db" ]]; then
    leaf_code='from django.db.migrations.loader import MigrationLoader; loader = MigrationLoader(None, ignore_no_migrations=True); [print(f"{app}\t{name}") for app, name in sorted(loader.graph.leaf_nodes())]'
    run_release_command \
        "$INSTANCE" "$TARGET_SHA" "$DB_NAME" \
        python manage.py shell --no-imports -c "$leaf_code" \
        > "$TARGETS_FILE"
    chmod 644 "$TARGETS_FILE"

    echo "Migration rollback plan:"
    "$SCRIPT_DIR/server/dw-run.sh" "$INSTANCE" \
        python manage.py rollback_migrations --targets-file "$TARGETS_FILE"
    confirm_rollback
    take_safety_backup
    stop_instance_services_strict "$INSTANCE"

    if ! "$SCRIPT_DIR/server/dw-run.sh" "$INSTANCE" \
        python manage.py rollback_migrations \
        --targets-file "$TARGETS_FILE" \
        --apply; then
        echo "ERROR: Reverse migrations failed; services remain stopped." >&2
        echo "Restore the safety pair with:" >&2
        echo "  sudo $0 $INSTANCE $CURRENT_SHORT --restore-backup" >&2
        exit 1
    fi

    run_release_command "$INSTANCE" "$TARGET_SHA" "$DB_NAME" \
        python manage.py migrate --check
    run_release_command "$INSTANCE" "$TARGET_SHA" "$DB_NAME" \
        python manage.py check
    switch_instance_release "$INSTANCE" "$TARGET_SHA"
    chown -h "$INST_USER:$INST_USER" "$INSTANCE_DIR/app"
    start_services
    write_deploy_state \
        "$INSTANCE" "$CURRENT_SHA" "$TARGET_SHA" "$INST_USER" \
        "$TRACKED_REF" "rollback-latest-db"
else
    if ! TARGET_BACKUP="$(newest_predeploy_backup_for_sha "$BACKUP_DIR" "$TARGET_SHORT")"; then
        echo "ERROR: no paired backup found for $TARGET_SHORT in $BACKUP_DIR" >&2
        exit 1
    fi
    echo "Paired target backup: $TARGET_BACKUP"
    confirm_rollback
    take_safety_backup

    RESTORE_DB="${DB_NAME}_rollback_restore_$(date +%Y%m%d_%H%M%S)_$$"
    OLD_DB="${DB_NAME}_rollback_old_$(date +%Y%m%d_%H%M%S)_$$"
    sudo -u postgres createdb --owner "$DB_USER" "$RESTORE_DB"
    gunzip -c "$TARGET_BACKUP" | \
        sudo -u postgres psql -v ON_ERROR_STOP=1 "$RESTORE_DB" >/dev/null
    run_release_command "$INSTANCE" "$TARGET_SHA" "$RESTORE_DB" \
        python manage.py migrate --check
    run_release_command "$INSTANCE" "$TARGET_SHA" "$RESTORE_DB" \
        python manage.py check

    stop_instance_services_strict "$INSTANCE"
    sudo -u postgres psql \
        -v ON_ERROR_STOP=1 \
        -v db_name="$DB_NAME" \
        -v restore_db="$RESTORE_DB" \
        -v old_db="$OLD_DB" \
        postgres <<'EOSQL'
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE datname IN (:'db_name', :'restore_db')
  AND pid <> pg_backend_pid();
SELECT format('ALTER DATABASE %I RENAME TO %I', :'db_name', :'old_db') \gexec
SELECT format('ALTER DATABASE %I RENAME TO %I', :'restore_db', :'db_name') \gexec
EOSQL
    RESTORE_DB=""
    switch_instance_release "$INSTANCE" "$TARGET_SHA"
    chown -h "$INST_USER:$INST_USER" "$INSTANCE_DIR/app"
    start_services
    write_deploy_state \
        "$INSTANCE" "$CURRENT_SHA" "$TARGET_SHA" "$INST_USER" \
        "$TRACKED_REF" "rollback-backup"
    sudo -u postgres dropdb --if-exists "$OLD_DB"
fi

echo "$INSTANCE now runs $TARGET_SHORT."
