#!/bin/bash
set -euo pipefail

# ==========================================================================
# MariaDB → PostgreSQL Migration
# ==========================================================================
#
# Production mode:
#   sudo ./scripts/migrate_mariadb_to_postgres.sh <client>-<env> <mariadb-source-db>
#   Example: sudo ./scripts/migrate_mariadb_to_postgres.sh msm-prod jobs_manager
#
# Local dry-run mode (validates migration using a production backup):
#   source .venv/bin/activate
#   bash scripts/migrate_mariadb_to_postgres.sh --local
#
# The core migration steps are identical in both modes:
#   capture row counts, dumpdata, create PG DB, migrate,
#   truncate content types, loaddata, verify counts.
#
# .env is NEVER edited. MariaDB-targeting commands use env var overrides.
#
# ==========================================================================

# --- Detect mode ---
MODE="production"
if [[ "${1:-}" == "--local" ]]; then
    MODE="local"
    shift
fi

# ==========================================================================
# Mode-specific setup
# ==========================================================================

if [[ "$MODE" == "production" ]]; then
    if [[ $EUID -ne 0 ]]; then
        echo "ERROR: Production mode must be run as root (use sudo)."
        exit 1
    fi

    if [[ $# -ne 2 ]]; then
        echo "Usage: $0 <client>-<env> <mariadb-source-db>"
        echo "       $0 msm-prod jobs_manager"
        echo "       $0 --local"
        exit 1
    fi

    INSTANCE="$1"
    MARIA_SOURCE_DB="$2"
    INSTANCE_DIR="/opt/docketworks/instances/$INSTANCE"
    ENV_FILE="$INSTANCE_DIR/.env"
    CODE_DIR="$INSTANCE_DIR/code"
    SERVICE="gunicorn-$INSTANCE"
    SHARED_VENV="/opt/docketworks/.venv"
    INSTANCE_USER="dw-$INSTANCE"
    SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
    DUMP_FILE="/tmp/dw_${INSTANCE}_dump.json"
    MYSQL_COUNTS="/tmp/dw_${INSTANCE}_mysql_counts.txt"
    PG_COUNTS="/tmp/dw_${INSTANCE}_pg_counts.txt"
    LOGFILE="$INSTANCE_DIR/logs/mysql_to_postgres_migration_$(date +%Y%m%d_%H%M%S).log"

    if [[ ! -f "$ENV_FILE" ]]; then
        echo "ERROR: .env not found at $ENV_FILE"
        exit 1
    fi

    # Read database config from .env (PostgreSQL target)
    set -a; source "$ENV_FILE"; set +a

    if [[ -z "${DB_NAME:-}" || -z "${DB_USER:-}" || -z "${DB_PASSWORD:-}" ]]; then
        echo "ERROR: DB_NAME, DB_USER, and DB_PASSWORD must be set in $ENV_FILE"
        exit 1
    fi

    PG_DB="$DB_NAME"
    MARIA_ENV="DB_ENGINE=django.db.backends.mysql DB_NAME=$DB_NAME"

    # dw_run: execute as instance user with venv and env
    # Optional first arg: env var overrides (detected by containing "=")
    dw_run() {
        local env_prefix=""
        if [[ "${1:-}" == *"="* ]]; then
            env_prefix="$1"
            shift
        fi
        local tmpscript
        tmpscript=$(mktemp /tmp/dw_run_XXXXXX.sh)
        cat > "$tmpscript" <<DWEOF
source '$SHARED_VENV/bin/activate'
set -a; source '$ENV_FILE'; set +a
cd '$CODE_DIR'
$env_prefix $(printf '%q ' "$@")
DWEOF
        chmod +x "$tmpscript"
        sudo -u "$INSTANCE_USER" bash "$tmpscript"
        local rc=$?
        rm -f "$tmpscript"
        return $rc
    }

else
    # Local mode
    PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
    cd "$PROJECT_DIR"

    SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
    ENV_FILE="$PROJECT_DIR/.env"

    if [[ ! -f "$ENV_FILE" ]]; then
        echo "ERROR: .env not found at $ENV_FILE"
        exit 1
    fi

    # Read database config from .env
    set -a; source "$ENV_FILE"; set +a

    if [[ -z "${DB_NAME:-}" || -z "${DB_USER:-}" || -z "${DB_PASSWORD:-}" ]]; then
        echo "ERROR: DB_NAME, DB_USER, and DB_PASSWORD must be set in $ENV_FILE"
        exit 1
    fi

    MARIA_DB=jobs_manager_prod
    PG_DB="$DB_NAME"
    DUMP_FILE=/tmp/dw_mysql_to_pg.json
    MYSQL_COUNTS=/tmp/dw_mysql_counts.txt
    PG_COUNTS=/tmp/dw_pg_counts.txt
    SQL_DUMP="$PROJECT_DIR/restore/jobs_manager_backup_20260327.sql"
    LOGFILE="$PROJECT_DIR/logs/mysql_to_postgres_dryrun_$(date +%Y%m%d_%H%M%S).log"
    MARIA_ENV="DB_ENGINE=django.db.backends.mysql DB_NAME=$MARIA_DB"

    # dw_run: passthrough with optional env var overrides
    dw_run() {
        if [[ "${1:-}" == *"="* ]]; then
            local -a env_vars=()
            for var in $1; do
                env_vars+=("$var")
            done
            shift
            env "${env_vars[@]}" "$@"
        else
            "$@"
        fi
    }
fi

# --- Logging ---
mkdir -p "$(dirname "$LOGFILE")"
exec > >(tee -a "$LOGFILE") 2>&1

log() { echo ""; echo "=== $1"; echo "=== $(date -Iseconds)"; }
check_ok() { echo "  CHECK: $1"; }
check_fail() { echo "  FAILED: $1"; echo "  STOPPING."; exit 1; }

pause() {
    if [[ "$MODE" == "local" ]]; then
        echo ""
        echo "----------------------------------------------------------------------"
        echo "  PHASE COMPLETE: $1"
        echo "  Review the output above. Press Enter to continue, Ctrl+C to abort."
        echo "----------------------------------------------------------------------"
        read -r
    fi
}

echo "=========================================================================="
echo "  MariaDB → PostgreSQL Migration"
echo "  Mode:    $MODE"
echo "  Started: $(date -Iseconds)"
echo "  Log:     $LOGFILE"
echo "=========================================================================="


# ==========================================================================
# LOCAL-ONLY: Setup and load MariaDB dump
# ==========================================================================

if [[ "$MODE" == "local" ]]; then

    log "PHASE 0: Setup"

    log "0.1 — Verify mysqlclient is available"
    python -c "import MySQLdb; print('mysqlclient installed OK')" || {
        echo "mysqlclient not found. Installing..."
        pip install mysqlclient
        python -c "import MySQLdb; print('mysqlclient installed OK')"
    }

    log "0.2 — Verify SQL dump exists"
    if [[ ! -f "$SQL_DUMP" ]]; then
        check_fail "SQL dump not found at $SQL_DUMP"
    fi
    ls -lh "$SQL_DUMP"

    pause "Phase 0: Setup"

    # ------------------------------------------------------------------
    log "PHASE 1: Load MariaDB Dump (simulates production state)"

    log "1.1 — Create MariaDB database"
    sudo mysql <<EOF
DROP DATABASE IF EXISTS $MARIA_DB;
CREATE DATABASE $MARIA_DB CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
GRANT ALL PRIVILEGES ON ${MARIA_DB}.* TO '${DB_USER}'@'localhost' IDENTIFIED BY '${DB_PASSWORD}';
FLUSH PRIVILEGES;
EOF
    check_ok "Database $MARIA_DB created"

    log "1.2 — Verify MariaDB access"
    mysql -u "$DB_USER" -p"$DB_PASSWORD" -e "SELECT 'MariaDB connection OK' AS status;" || \
        check_fail "Cannot connect to MariaDB as $DB_USER"

    log "1.3 — Load the SQL dump (this takes several minutes for 1.4GB)"
    echo "  Loading $SQL_DUMP into $MARIA_DB ..."
    mysql -u "$DB_USER" -p"$DB_PASSWORD" -D "$MARIA_DB" \
        --execute="source $SQL_DUMP"
    check_ok "SQL dump loaded"

    log "1.4 — Verify the load"
    TABLE_COUNT=$(mysql -u "$DB_USER" -p"$DB_PASSWORD" "$MARIA_DB" -N -e "SHOW TABLES;" | wc -l)
    echo "  Table count: $TABLE_COUNT"
    if [[ "$TABLE_COUNT" -lt 50 ]]; then
        check_fail "Expected 60+ tables, got $TABLE_COUNT"
    fi

    mysql -u "$DB_USER" -p"$DB_PASSWORD" "$MARIA_DB" -e "
SELECT 'workflow_job' AS tbl, COUNT(*) AS cnt FROM workflow_job
UNION ALL SELECT 'workflow_client', COUNT(*) FROM workflow_client
UNION ALL SELECT 'workflow_staff', COUNT(*) FROM workflow_staff
UNION ALL SELECT 'job_costline', COUNT(*) FROM job_costline
UNION ALL SELECT 'job_costset', COUNT(*) FROM job_costset;
"

    log "1.5 — Check production migration state"
    mysql -u "$DB_USER" -p"$DB_PASSWORD" "$MARIA_DB" -e \
        "SELECT app, name FROM django_migrations ORDER BY id DESC LIMIT 15;"

    pause "Phase 1: MariaDB dump loaded"

    # ------------------------------------------------------------------
    log "PHASE 2: Apply pending migrations to MariaDB"

    log "2.1 — Verify Django connects to MariaDB"
    dw_run "$MARIA_ENV" python manage.py shell -c "
from django.db import connection
cursor = connection.cursor()
cursor.execute('SELECT 1')
print('Django->MariaDB OK:', cursor.fetchone())
" || check_fail "Django cannot connect to MariaDB"

    log "2.2 — Check pending migrations (these will run on production too)"
    echo "  Unapplied migrations:"
    dw_run "$MARIA_ENV" python manage.py showmigrations | grep '\[ \]' || echo "  (none — all applied)"

    log "2.3 — Run migrations against MariaDB (simulates production deployment)"
    dw_run "$MARIA_ENV" python manage.py migrate --no-input || check_fail "Migration against MariaDB failed — production would also fail"

    log "2.4 — Verify all migrations applied"
    UNAPPLIED=$(dw_run "$MARIA_ENV" python manage.py showmigrations | { grep '\[ \]' || true; } | wc -l)
    if [[ "$UNAPPLIED" -gt 0 ]]; then
        dw_run "$MARIA_ENV" python manage.py showmigrations | grep '\[ \]'
        check_fail "$UNAPPLIED unapplied migrations remain"
    fi
    check_ok "All migrations applied"

    log "2.5 — Verify table names after migration"
    mysql -u "$DB_USER" -p"$DB_PASSWORD" "$MARIA_DB" -e "SHOW TABLES;" | sort

    pause "Phase 2: Migrations applied to MariaDB"
fi


# ==========================================================================
# PRODUCTION-ONLY: Stop app, copy MariaDB, prepare for migration
# ==========================================================================

if [[ "$MODE" == "production" ]]; then
    log "Step 1: Stopping $SERVICE..."
    systemctl stop "$SERVICE"

    log "Step 2: Copy MariaDB $MARIA_SOURCE_DB → $DB_NAME"
    echo "  Creating MariaDB database $DB_NAME and copying data..."
    mysql -e "DROP DATABASE IF EXISTS \`$DB_NAME\`;"
    mysql -e "CREATE DATABASE \`$DB_NAME\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
    mysqldump "$MARIA_SOURCE_DB" | mysql "$DB_NAME"
    check_ok "MariaDB $MARIA_SOURCE_DB copied to $DB_NAME"

    log "Step 3: Grant $DB_USER access to MariaDB $DB_NAME"
    mysql -e "GRANT ALL PRIVILEGES ON \`$DB_NAME\`.* TO '$DB_USER'@'localhost' IDENTIFIED BY '$DB_PASSWORD'; FLUSH PRIVILEGES;"
    check_ok "Granted $DB_USER access to MariaDB $DB_NAME"

    log "Step 4: Run pending migrations against MariaDB $DB_NAME"
    dw_run "$MARIA_ENV" python manage.py migrate --no-input || check_fail "Migration against MariaDB failed"
    UNAPPLIED=$(dw_run "$MARIA_ENV" python manage.py showmigrations | { grep '\[ \]' || true; } | wc -l)
    if [[ "$UNAPPLIED" -gt 0 ]]; then
        dw_run "$MARIA_ENV" python manage.py showmigrations | grep '\[ \]'
        check_fail "$UNAPPLIED unapplied migrations remain"
    fi
    check_ok "All migrations applied to MariaDB $DB_NAME"
fi


# ==========================================================================
# CORE MIGRATION (identical in both modes)
# ==========================================================================

# --- Capture MariaDB baseline row counts ---
log "Core Step 1: Capturing MariaDB baseline row counts..."
dw_run "$MARIA_ENV" python manage.py shell -c "
from django.apps import apps
total = 0
for model in sorted(apps.get_models(), key=lambda m: m._meta.label):
    count = model.objects.count()
    if count > 0:
        print(f'{model._meta.label}: {count}')
        total += count
print(f'TOTAL: {total}')
" | tee "$MYSQL_COUNTS"

# --- Dump data from MariaDB ---
log "Core Step 2: Dumping data from MariaDB..."
echo "  NO --natural-foreign, NO --natural-primary (preserves exact UUIDs/PKs)"
dw_run "$MARIA_ENV" python manage.py dumpdata \
    --exclude contenttypes --exclude auth.permission \
    --indent 2 \
    --output "$DUMP_FILE" || check_fail "dumpdata from MariaDB failed"
echo "  Dump complete: $(wc -c < "$DUMP_FILE") bytes"
check_ok "Data dumped to $DUMP_FILE"

# --- Create PostgreSQL database ---
log "Core Step 3: Creating PostgreSQL database..."
sudo -u postgres "$SCRIPT_DIR/setup_database.sh" \
    --db "$PG_DB" --user "$DB_USER" --password "$DB_PASSWORD" --drop || \
    check_fail "PostgreSQL database creation failed"

# --- Run Django migrate on PostgreSQL ---
log "Core Step 4: Running Django migrate on PostgreSQL..."
dw_run python manage.py migrate --no-input || check_fail "PostgreSQL migration failed"
check_ok "All migrations applied to PostgreSQL"

# --- Truncate auto-generated content types ---
log "Core Step 5: Truncating auto-generated content types..."
PGPASSWORD="$DB_PASSWORD" psql -h 127.0.0.1 -U "$DB_USER" "$PG_DB" \
    -c "TRUNCATE django_content_type CASCADE;"
check_ok "Content types truncated"

# --- Load data into PostgreSQL ---
log "Core Step 6: Loading data into PostgreSQL (this takes several minutes)..."
dw_run python manage.py loaddata "$DUMP_FILE" || check_fail "loaddata into PostgreSQL failed"
check_ok "Data loaded into PostgreSQL"

# --- Verify row counts match ---
log "Core Step 7: Verifying row counts..."
dw_run python manage.py shell -c "
from django.apps import apps
total = 0
for model in sorted(apps.get_models(), key=lambda m: m._meta.label):
    count = model.objects.count()
    if count > 0:
        print(f'{model._meta.label}: {count}')
        total += count
print(f'TOTAL: {total}')
" | tee "$PG_COUNTS"

echo ""
echo "  Row count diff (MariaDB vs PostgreSQL):"
if diff "$MYSQL_COUNTS" "$PG_COUNTS"; then
    check_ok "Row counts match exactly"
else
    echo "  WARNING: Differences found above — review carefully."
    echo "  If business model counts differ: STOP and investigate."
fi

pause "Core migration complete"


# ==========================================================================
# Post-migration
# ==========================================================================

if [[ "$MODE" == "production" ]]; then
    # --- Restart application ---
    log "Restarting $SERVICE..."
    systemctl start "$SERVICE"

    echo ""
    echo "=========================================================================="
    echo "  Migration complete!"
    echo "=========================================================================="
    echo "  Finished: $(date -Iseconds)"
    echo "  Log file: $LOGFILE"
    echo "  Verify the site at: https://$INSTANCE.docketworks.site"
    echo "  Dump file preserved at: $DUMP_FILE"
    echo ""
    echo "  Once verified, you can remove MariaDB:"
    echo "    apt remove --purge mariadb-server"

else
    # --- Local: Verification ---
    log "Verification: UUID spot-check (PostgreSQL)"
    PGPASSWORD="$DB_PASSWORD" psql -h 127.0.0.1 -U "$DB_USER" "$PG_DB" -c "
SELECT id, job_number, name FROM workflow_job ORDER BY job_number DESC LIMIT 5;
"

    log "Verification: UUID spot-check (MariaDB — for comparison)"
    mysql -u "$DB_USER" -p"$DB_PASSWORD" "$MARIA_DB" -e "
SELECT id, job_number, name FROM workflow_job ORDER BY job_number DESC LIMIT 5;
"

    log "Verification: Django health checks"
    python manage.py check || check_fail "Django check failed"
    check_ok "Django check passed"

    UNAPPLIED=$(python manage.py showmigrations | { grep '\[ \]' || true; } | wc -l)
    if [[ "$UNAPPLIED" -gt 0 ]]; then
        check_fail "$UNAPPLIED unapplied migrations on PostgreSQL"
    fi
    check_ok "All migrations applied"

    pause "Verification complete"

    # --- Local: Dev Setup ---
    log "Dev Setup: Load Company Defaults"
    python manage.py loaddata apps/workflow/fixtures/company_defaults.json
    python scripts/restore_checks/check_company_defaults.py

    log "Dev Setup: Load AI Providers"
    python manage.py loaddata apps/workflow/fixtures/ai_providers.json
    python scripts/restore_checks/check_ai_providers.py

    log "Dev Setup: Test Django ORM"
    python scripts/restore_checks/check_django_orm.py

    log "Dev Setup: Set Up Development Logins"
    python scripts/setup_dev_logins.py
    python scripts/restore_checks/check_admin_user.py

    log "Dev Setup: Create Dummy JobFiles"
    python scripts/recreate_jobfiles.py
    python scripts/restore_checks/check_jobfiles.py

    log "Dev Setup: Fix Shop Client Name"
    python scripts/restore_checks/fix_shop_client.py
    python scripts/restore_checks/check_shop_client.py

    log "Dev Setup: Verify Test Client"
    python scripts/restore_checks/check_test_client.py

    pause "Dev setup complete"

    # --- Local: Smoke Tests ---
    log "Smoke Tests: Test serializers"
    python scripts/restore_checks/test_serializers.py --verbose

    log "Smoke Tests: Test Kanban API"
    python scripts/restore_checks/test_kanban_api.py

    echo ""
    echo "  Manual checks (start the dev server first):"
    echo "  [ ] Log in with defaultadmin@example.com / Default-admin-password"
    echo "  [ ] Kanban board loads with jobs"
    echo "  [ ] Job detail page shows cost lines and events"
    echo "  [ ] Client page loads with contacts"

    pause "Smoke tests"

    # --- Local: Done ---
    echo ""
    echo "=========================================================================="
    echo "  Migration Dry Run COMPLETE"
    echo "  Finished: $(date -Iseconds)"
    echo "  Log:      $LOGFILE"
    echo "=========================================================================="
    echo ""
    echo "  MariaDB database '$MARIA_DB' is still available for comparison."
    echo "  To drop it when done: sudo mysql -e 'DROP DATABASE $MARIA_DB;'"
    echo ""
    echo "  Dump file preserved at: $DUMP_FILE"
fi
