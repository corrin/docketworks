# Dev Dry Run: MariaDB → PostgreSQL Migration

## Context

Production runs on MariaDB (`jobs_manager` database). The codebase has been migrated to PostgreSQL but production hasn't been cut over yet. This dry run validates the migration runbook (`docs/production-mysql-to-postgres-migration.md`) using a real production backup before we do it for real.

**Backup:** `restore/jobs_manager_backup_20260327.sql` (1.4GB MariaDB dump, 62 tables)

**Key finding:** The prod dump has a mix of old (`workflow_client`, `workflow_job`, `workflow_staff`) and new (`client_contact`, `job_costline`) table names — some rename migrations have been applied in prod, others haven't. Running `migrate` against MariaDB will apply the remaining renames before we dump.

**Script:** `scripts/migrate_mariadb_to_postgres.sh --local` (same script used for production, with `--local` flag for dry run mode).

---

## PHASE 0: Setup

### 0.1 — Save current .env
```bash
cp .env .env.backup.pre-migration-dryrun
```

### 0.2 — Verify mysqlclient is available
```bash
python -c "import MySQLdb; print('mysqlclient version:', MySQLdb.__version__)"
```
If missing: `pip install mysqlclient`

---

## PHASE 1: Load MariaDB Dump (simulates production state)

### 1.1 — Create MariaDB database
```bash
sudo mysql <<'EOF'
CREATE DATABASE IF NOT EXISTS jobs_manager_prod CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
GRANT ALL PRIVILEGES ON jobs_manager_prod.* TO 'dw_msm_dev'@'localhost' IDENTIFIED BY 'cur-fiasco-pectin';
FLUSH PRIVILEGES;
EOF
```

### 1.2 — Verify MariaDB access
```bash
mysql -u dw_msm_dev -p'cur-fiasco-pectin' -e "SELECT 'MariaDB connection OK' AS status;"
```

### 1.3 — Load the SQL dump
The dump targets `jobs_manager` but we're loading into `jobs_manager_prod`, so we use `-D` to override:
```bash
mysql -u dw_msm_dev -p'cur-fiasco-pectin' -D jobs_manager_prod --execute="source /home/corrin/src/docketworks/restore/jobs_manager_backup_20260327.sql"
```
**Takes several minutes** (1.4GB).

### 1.4 — Verify the load
```bash
mysql -u dw_msm_dev -p'cur-fiasco-pectin' jobs_manager_prod -e "SHOW TABLES;" | wc -l
```
**Expected:** 63 (62 tables + header).

```bash
mysql -u dw_msm_dev -p'cur-fiasco-pectin' jobs_manager_prod -e "
SELECT 'workflow_job' AS tbl, COUNT(*) AS cnt FROM workflow_job
UNION ALL SELECT 'workflow_client', COUNT(*) FROM workflow_client
UNION ALL SELECT 'workflow_staff', COUNT(*) FROM workflow_staff
UNION ALL SELECT 'job_costline', COUNT(*) FROM job_costline
UNION ALL SELECT 'job_costset', COUNT(*) FROM job_costset;
"
```

### 1.5 — Check production migration state
```bash
mysql -u dw_msm_dev -p'cur-fiasco-pectin' jobs_manager_prod -e "SELECT app, name FROM django_migrations ORDER BY id DESC LIMIT 10;"
```
Records which migrations production has already applied.

---

## PHASE 2: Point Django at MariaDB and Apply Pending Migrations

Simulates deploying latest code to production (which runs `manage.py migrate`).

### 2.1 — Edit .env for MariaDB
Set these values in `.env`:
```
DB_ENGINE=django.db.backends.mysql
DB_NAME=jobs_manager_prod
```
Leave `DB_USER`, `DB_PASSWORD` unchanged.

### 2.2 — Verify Django connects to MariaDB
```bash
python manage.py shell -c "from django.db import connection; cursor = connection.cursor(); cursor.execute('SELECT 1'); print('Django->MariaDB OK:', cursor.fetchone())"
```

### 2.3 — Check pending migrations
```bash
python manage.py showmigrations | grep '\[ \]'
```
Record this output — these are the migrations that will run on production when we deploy.

### 2.4 — Run migrations against MariaDB
```bash
python manage.py migrate --no-input
```
**CRITICAL:** If any migration fails, STOP. This means the production deployment would also fail.

### 2.5 — Verify all migrations applied
```bash
python manage.py showmigrations | grep '\[ \]'
```
**Expected:** No output.

### 2.6 — Verify table renames completed
```bash
mysql -u dw_msm_dev -p'cur-fiasco-pectin' jobs_manager_prod -e "SHOW TABLES;" | sort
```
Old names (`workflow_client`, `workflow_job`, `workflow_staff`) should now be renamed.

---

## PHASE 3: Migration Runbook Steps 2–9

Now following `docs/production-mysql-to-postgres-migration.md` exactly.

### 3.1 — Step 2: Capture MariaDB row counts (baseline)
```bash
python manage.py shell -c "
from django.apps import apps
total = 0
for model in sorted(apps.get_models(), key=lambda m: m._meta.label):
    count = model.objects.count()
    if count > 0:
        print(f'{model._meta.label}: {count}')
        total += count
print(f'TOTAL: {total}')
" | tee /tmp/dw_mysql_counts.txt
```

### 3.2 — Step 3: Dump data from MariaDB
```bash
python manage.py dumpdata \
    --exclude contenttypes \
    --exclude auth.permission \
    --indent 2 \
    --output /tmp/dw_mysql_to_pg.json
```
**NO** `--natural-foreign`, **NO** `--natural-primary` (preserves exact UUIDs/PKs).

**Check:**
```bash
ls -lh /tmp/dw_mysql_to_pg.json
```

### 3.3 — Step 4: Create PostgreSQL database
```bash
sudo -u postgres /home/corrin/src/docketworks/scripts/setup_database.sh --db dw_msm_dev --user dw_msm_dev --password cur-fiasco-pectin --drop
```
**Check:** Output shows `Database dw_msm_dev ready.`

### 3.4 — Step 5: Switch .env to PostgreSQL
Edit `.env`:
```
DB_ENGINE=django.db.backends.postgresql
DB_NAME=dw_msm_dev
```

### 3.5 — Step 6: Run migrations on PostgreSQL
```bash
python manage.py migrate --no-input
```
**Check:** All migrations show OK.

### 3.6 — Step 7: Truncate auto-generated content types
```bash
PGPASSWORD="cur-fiasco-pectin" psql -h 127.0.0.1 -U dw_msm_dev dw_msm_dev -c "TRUNCATE django_content_type CASCADE;"
```
**Check:** Output shows `TRUNCATE TABLE`.

### 3.7 — Step 8: Load data into PostgreSQL
```bash
python manage.py loaddata /tmp/dw_mysql_to_pg.json
```
**Takes several minutes.** Check: Shows `Installed NNNNN object(s) from 1 fixture(s)`.

### 3.8 — Step 9: Verify row counts match
```bash
python manage.py shell -c "
from django.apps import apps
total = 0
for model in sorted(apps.get_models(), key=lambda m: m._meta.label):
    count = model.objects.count()
    if count > 0:
        print(f'{model._meta.label}: {count}')
        total += count
print(f'TOTAL: {total}')
" | tee /tmp/dw_pg_counts.txt
```

```bash
diff /tmp/dw_mysql_counts.txt /tmp/dw_pg_counts.txt
```
**Expected:** All business model counts identical. Only `auth.Permission` and `contenttypes.ContentType` may differ (regenerated by migrate).

**If any business model count differs: STOP.**

---

## PHASE 4: Verification (Runbook Steps 10–11)

### 4.1 — UUID spot-check
```bash
PGPASSWORD="cur-fiasco-pectin" psql -h 127.0.0.1 -U dw_msm_dev dw_msm_dev -c "
SELECT id, job_number, name FROM workflow_job ORDER BY job_number DESC LIMIT 5;
"
```

Compare against MariaDB:
```bash
mysql -u dw_msm_dev -p'cur-fiasco-pectin' jobs_manager_prod -e "
SELECT id, job_number, name FROM workflow_job ORDER BY job_number DESC LIMIT 5;
"
```
**Expected:** Identical UUIDs, job numbers, and names.

### 4.2 — Django health checks
```bash
python manage.py check
python manage.py showmigrations | grep '\[ \]'
```
**Expected:** No issues, no unapplied migrations.

---

## PHASE 5: Dev Setup (Restore Process Steps 10–17)

### 5.1 — Load Company Defaults
```bash
python manage.py loaddata apps/workflow/fixtures/company_defaults.json
```
```bash
python scripts/restore_checks/check_company_defaults.py
```

### 5.2 — Load AI Providers
```bash
python manage.py loaddata apps/workflow/fixtures/ai_providers.json
```
```bash
python scripts/restore_checks/check_ai_providers.py
```

### 5.3 — Test Django ORM
```bash
python scripts/restore_checks/check_django_orm.py
```

### 5.4 — Set Up Development Logins
```bash
python scripts/setup_dev_logins.py
```
```bash
python scripts/restore_checks/check_admin_user.py
```

### 5.5 — Create Dummy JobFiles
```bash
python scripts/recreate_jobfiles.py
```
```bash
python scripts/restore_checks/check_jobfiles.py
```

### 5.6 — Fix Shop Client Name
```bash
python scripts/restore_checks/fix_shop_client.py
```
```bash
python scripts/restore_checks/check_shop_client.py
```

### 5.7 — Verify Test Client
```bash
python scripts/restore_checks/check_test_client.py
```

---

## PHASE 6: Smoke Tests

### 6.1 — Test serializers
```bash
python scripts/restore_checks/test_serializers.py --verbose
```

### 6.2 — Test Kanban API
```bash
python scripts/restore_checks/test_kanban_api.py
```

### 6.3 — Manual checks (with dev server running)
- [ ] Log in with `defaultadmin@example.com` / `Default-admin-password`
- [ ] Kanban board loads with jobs
- [ ] Job detail page shows cost lines and events
- [ ] Client page loads with contacts

---

## PHASE 7: Cleanup and .env Restoration

### 7.1 — Restore .env
Ensure `.env` has:
```
DB_ENGINE=django.db.backends.postgresql
DB_NAME=dw_msm_dev
```
(Or remove `DB_ENGINE` entirely — defaults to postgresql.)

### 7.2 — .env changes summary

| Phase | DB_ENGINE | DB_NAME |
|---|---|---|
| Start | _(not set → postgresql)_ | `dw_msm_dev` |
| Phase 2 | `django.db.backends.mysql` | `jobs_manager_prod` |
| Phase 3.4 | `django.db.backends.postgresql` | `dw_msm_dev` |

---

## Issues to Fix Before Production

1. [x] `scripts/migrate_mariadb_to_postgres.sh`: Removed `--natural-foreign --natural-primary` flags
2. [x] `scripts/migrate_mariadb_to_postgres.sh`: Added content type truncation step
3. [x] `scripts/migrate_mariadb_to_postgres.sh`: Removed `--exclude admin.logentry`
4. [x] `scripts/migrate_mariadb_to_postgres.sh`: Added `.env` switch to PostgreSQL
5. [x] `scripts/migrate_mariadb_to_postgres.sh`: Added baseline row count capture and diff
6. [x] Merged dry run and production scripts into one (`--local` flag)
7. [ ] **Runbook:** After successful dry run, tick the pre-migration checklist item

## Critical Files
- `.env` — edited twice during process
- `docs/production-mysql-to-postgres-migration.md` — the runbook being validated
- `scripts/migrate_mariadb_to_postgres.sh` — unified migration script (production + local dry run)
- `scripts/setup_database.sh` — creates PostgreSQL database
- `restore/jobs_manager_backup_20260327.sql` — the production dump
