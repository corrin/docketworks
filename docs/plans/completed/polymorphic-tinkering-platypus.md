# Fix Production Migration Script

## Current change: Stop editing .env, use env var overrides

### Problem

The script edits `.env` to toggle between MariaDB and PostgreSQL. If the script dies mid-way, `.env` is left in a broken state (which happened during the dry run).

### Approach

Make `dw_run` accept optional env var overrides. MariaDB-targeting commands pass overrides; everything else uses `.env` as-is (PostgreSQL).

**Local mode `dw_run`:**
```bash
dw_run() {
    local env_prefix="${1:-}"
    if [[ "$env_prefix" == *"="* ]]; then
        shift
        eval "$env_prefix $*"
    else
        eval "$*"
    fi
}
```

**Production mode `dw_run`:**
```bash
dw_run() {
    local env_prefix="${1:-}"
    if [[ "$env_prefix" == *"="* ]]; then
        shift
        sudo -u "$INSTANCE_USER" bash -c "
            source '$SHARED_VENV/bin/activate'
            set -a; source '$ENV_FILE'; set +a
            cd '$CODE_DIR'
            $env_prefix $*
        "
    else
        sudo -u "$INSTANCE_USER" bash -c "
            source '$SHARED_VENV/bin/activate'
            set -a; source '$ENV_FILE'; set +a
            cd '$CODE_DIR'
            $*
        "
    fi
}
```

**Usage:**
```bash
# MariaDB commands — pass overrides
MARIA_ENV="DB_ENGINE=django.db.backends.mysql DB_NAME=$MARIA_DB"
dw_run "$MARIA_ENV" python manage.py shell -c "..."
dw_run "$MARIA_ENV" python manage.py dumpdata ...

# PostgreSQL commands — no overrides, .env is already correct
dw_run python manage.py migrate --no-input
dw_run python manage.py loaddata "$DUMP_FILE"
```

### What to remove

- Phase 0.1: `.env` backup (no longer needed)
- Phase 2.1: Edit `.env` for MariaDB (replaced by env overrides)
- Core Step 4: Switch `.env` to PostgreSQL (no longer needed — .env never changed)
- Cleanup section: Verify/fix `.env` (no longer needed)
- Production Step 4: Switch `.env` to MariaDB (replaced by env overrides)

### File

`scripts/migrate_mariadb_to_postgres.sh`

### Also done

- Added Phase 5 (post-migration config: company phone + logos) to `docs/production-cutover-plan.md`
- Fixed production URL to `office.morrissheetmetal.co.nz` (not docketworks.site which is UAT)
