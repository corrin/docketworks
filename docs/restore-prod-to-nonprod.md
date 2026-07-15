# Restore Production to Non-Production

Restore a production backup to any non-production environment (dev or server instance). This guide is environment-agnostic: assume venv active, `.env` loaded, in the project root. All paths are relative.

The scrubbed dump is produced on prod by `manage.py backport_data_backup` and lives on the prod host at `restore/scrubbed_<DB_NAME>_<ts>.dump` under the project's `BASE_DIR`. Raw prod data never lands on disk on either host — `backport_data_backup` pipes `pg_dump` directly into a temp `_scrub` database, scrubs in place, then re-dumps the scrubbed copy.

## CRITICAL: Audit

**Everything typed into this terminal is audited for legal compliance.** Every command and its output is reviewed against this runbook, in order. Skipping steps, running them out of order, or working around errors instead of stopping are violations the audit catches.

## CRITICAL: No Workarounds

This process runs unattended on server instances with no user interaction. Any workaround you apply will fail silently in automated runs. If anything goes wrong, STOP and fix the underlying problem — do not skip the failing step, do not run subsequent steps, do not "patch and continue."

Sections must run in the order written. The Connect to Xero OAuth section is a hard gate — every later section assumes Xero is connected.

## Prerequisites

- `.env` configured with `DB_NAME`, `DB_USER`, `DB_PASSWORD`, and all other required variables.
- The scrubbed dump fetched from prod into `restore/`:
  ```bash
  scp prod-server:/path/to/docketworks/restore/scrubbed_<DB_NAME>_<ts>.dump restore/
  ```
- The fetched archive must pass the credential and migration-ledger verifier:
  ```bash
  python scripts/verify_scrubbed_backup.py \
    --allow-legacy-client-baseline \
    restore/scrubbed_<DB_NAME>_<ts>.dump
  ```
  This fails if the archive is unreadable, predates the July migration squash,
  or contains DB-backed external-system credentials. Do not restore a failing
  archive.
- **TEMPORARY KAN-278:** `--allow-legacy-client-baseline` exists only while
  production still uses the pre-cutover `client` app label. Remove this flag and
  the pre-migration cutover sections below after every production instance has
  migrated and produced a verified company-schema backup.
- The dump must be from a prod release at or after the July 2026 migration squash (baseline `*_baseline` migrations). Older dumps carry a `django_migrations` ledger the current graph cannot migrate — restore those under a matching pre-squash checkout instead (see `docs/updating.md`).
- Celery Beat stopped. Beat ticks against the DB and Xero on a timer; if it fires during the reset/restore it will block `DROP SCHEMA` or race `seed_xero_from_database`. Stop it before Reset Database; the Celery Beat section restarts it. The worker can stay running — it has nothing to do without Beat dispatches.
  - Dev: kill the `Celery Beat` task in its VS Code terminal.
  - Server: `sudo systemctl stop celery-beat-<instance>`

---

#### Verify Environment Configuration

**Check venv is active** (every bare `python` below depends on this):

```bash
python -c "import django; print(f'django {django.__version__} from {django.__file__}')" \
  || { echo "venv not active — run: source .venv/bin/activate"; exit 1; }
```

**Check `.env` is loaded:**

```bash
grep -E "^(DB_NAME|DB_USER|DB_HOST)=" .env
grep -q '^DB_PASSWORD=.' .env && echo "DB_PASSWORD is set"
export DB_PASSWORD=$(grep DB_PASSWORD .env | cut -d= -f2)
export DB_NAME=$(grep DB_NAME .env | cut -d= -f2)
export DB_USER=$(grep DB_USER .env | cut -d= -f2)
export DB_HOST=$(grep DB_HOST .env | cut -d= -f2)
```

**Must show:**

```
DB_NAME=dw_<client>_<env>
DB_USER=dw_<client>_<env>
DB_HOST=/var/run/postgresql
DB_PASSWORD is set
```

Note: If you're using Claude or similar, you need to specify these explicitly on all subsequent command lines rather than use environment variables.

#### Reset Database

Drop all tables by dropping and recreating the public schema:

```bash
python manage.py dbshell -- -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
```

**Check:**

```bash
python manage.py dbshell -- -c "\dt"
# Should return: Did not find any relations.
```

#### Restore the Dump

The scrubbed dump carries schema, data, and `django_migrations` together. `pg_restore` rebuilds all three in one shot.

```bash
PGPASSWORD="$DB_PASSWORD" pg_restore --no-owner --no-privileges --exit-on-error \
  -h "$DB_HOST" -U "$DB_USER" -d "$DB_NAME" \
  ./restore/scrubbed_<source-db>_<ts>.dump
```

#### Capture Pre-Migration State

**TEMPORARY KAN-278 CUTOVER STEP:** Remove this section after every production
instance has completed the client-to-company migration and produced a verified
company-schema backup.

The restored dump may use the schema of the production release while the
checkout contains newer models. Do not run current ORM code against that old
schema. Capture count-only evidence through raw SQL instead:

```bash
python scripts/restore_checks/capture_pre_migration_state.py
```

This requires the pre-KAN-278 `client_*` schema, verifies the squashed migration
ledger, and writes only aggregate counts to
`restore/pre_migration_state.json`. A missing table, unexpected new-schema
table, or empty production dataset is a hard stop.

#### Relabel the Legacy Client App

**TEMPORARY KAN-278 CUTOVER STEP:** The restored ledger and tables still use the
legacy `client` app label. Apply the same one-time, idempotent surgery that the
deployment workflow runs before Django migrations:

```bash
python manage.py relabel_client_app
```

This must complete successfully before `migrate`. It keeps the squashed
baseline, removes obsolete pre-squash ledger rows, and changes the app label and
table prefixes without creating a second baseline.

#### Apply Django Migrations

`django_migrations` rode along in the dump, so this only runs migrations the dev branch has beyond prod's state. On a fresh prod-aligned checkout it's a no-op.

```bash
python manage.py migrate
```

**Check:**

```bash
python scripts/restore_checks/check_post_migration_state.py
python scripts/restore_checks/check_django_orm.py
python manage.py showmigrations | grep '\[ \]'
# Expect no output.
```

The post-migration check compares against the captured counts and verifies the
client→company table cutover, Person/link ownership, job and call references,
merge structure, and persisted terminology. Any mismatch is a migration
failure; do not continue.

#### Load Company Defaults Fixture

For demo restores only, this replaces your real company name and logos with the
shipped DocketWorks demo values. Tenant installs should load their
instance-owned `/opt/docketworks/instances/<name>/company_defaults.json` copy
instead of the shared repo fixture.

```bash
python manage.py loaddata apps/workflow/fixtures/company_defaults.json
```

#### Reload Private Configuration

The scrubbed archive contains no DB-backed external-system configuration.
Restore only configuration owned by this non-production target.

**Local dev:** load the ignored local AI and Xero fixtures. Phone-provider
configuration intentionally remains absent so local Celery cannot contact the
production phone system.

```bash
python manage.py loaddata apps/workflow/fixtures/ai_providers.json
python manage.py loaddata apps/workflow/fixtures/xero_apps.json
python scripts/restore_checks/check_xero_app.py
python manage.py shell -c "from apps.crm.models import PhoneProviderSettings; assert not PhoneProviderSettings.objects.exists(), 'phone provider must be unconfigured on local dev'"
```

**Server instance:** regenerate and load the instance-owned private fixtures
from the root-owned credentials file:

```bash
sudo scripts/server/instance.sh reconfigure <client> <env>
```

#### Set Up Development Logins

```bash
python scripts/setup_dev_logins.py
```

Creates a default admin user and resets all staff passwords to defaults.

**Login credentials after restore:**
- Admin: `defaultadmin@example.com` / `Default-admin-password`
- All other staff: their email / `Default-staff-password`

#### Create Dummy Files for JobFile Instances

```bash
python scripts/recreate_jobfiles.py
```

#### Fix Shop Company Name

```bash
python scripts/restore_checks/fix_shop_company.py
```

#### Create Test Company

Creates the test company named per `CompanyDefaults.test_company_name` (e.g. `ABC Carpet Cleaning TEST IGNORE`) if it isn't already there. Idempotent. Required by Seed Database to Xero, which crashes if the company is missing.

```bash
python scripts/fix_test_company.py
```

**Expected output:** `Test company already exists: …` or `Created test company: …`.

#### Connect to Xero OAuth

**Dev only:** Before this step, **the user** must start ngrok, the backend, and the frontend in separate terminals. The agent must NEVER start these services on the user's behalf. See [development_session.md](development_session.md).

```bash
(cd frontend && npx tsx tests/scripts/xero-login.ts)
```

**What this does:**
This script automates the Xero OAuth login flow using Playwright. It navigates to the frontend, logs in with the default admin credentials, and completes the Xero OAuth authorization.

#### Configure Xero Connection

```bash
python manage.py xero --setup
```

**What this does:**
Configures all required Xero settings in CompanyDefaults:
1. Sets `xero_tenant_id` from connected organisation
2. Sets `xero_shortcode` for deep linking
3. Looks up payroll calendar by name and sets `xero_payroll_calendar_id`

**Expected output:**

```
Using organisation: [Tenant Name]
Tenant ID: [tenant-id-uuid]
Shortcode: [shortcode]
Payroll Calendar: Weekly Testing ([calendar-uuid])
Xero setup complete.
```

**Note:** Requires `xero_payroll_calendar_name` to be set in CompanyDefaults (loaded from fixture in Load Company Defaults).

`--setup` provisions any payroll calendar, earnings rates, or leave types that are present in the restored DB but missing from this Xero org (e.g. a fresh demo org), so the seed step below can match every backup pay item by name. The payroll calendar it creates is a weekly calendar anchored to a **Monday** (payroll posting requires Mon→Sun periods); `--setup` aborts if Xero hands back a calendar starting on any other day.

#### Sync Pay Items from Xero

```bash
python manage.py xero --configure-payroll
```

**Expected output:** `✓ XeroPayItem sync completed!`

#### Seed Database to Xero

**WARNING:** This step takes 10+ minutes. Run in background.

```bash
nohup python manage.py seed_xero_from_database > logs/seed_xero_output.log 2>&1 &
echo "Background process started, PID: $!"
```

**What this does:**
1. Clears production Xero IDs (companies, jobs, stock, purchase orders, staff)
2. Updates XeroAccount xero_ids from prod to dev Xero tenant (fetches from dev Xero, upserts by account_name)
3. Remaps XeroPayItem FK references (Job.default_xero_pay_item, CostLine.xero_pay_item) from prod UUIDs to dev UUIDs by matching pay item names
4. Links/creates contacts in Xero for all companies
5. Creates projects in Xero for all jobs
6. Deletes orphaned invoices, re-creates job-linked invoices in dev Xero
7. Deletes orphaned quotes, re-creates job-linked quotes in dev Xero
8. Syncs stock items to Xero inventory
9. Links/creates payroll employees for all active staff (uses Staff UUID in job_title for reliable re-linking)
10. Sets `enable_xero_sync = True` in CompanyDefaults (Xero sync is blocked until this point)

**Monitor progress:**

```bash
tail -f logs/seed_xero_output.log
# Press Ctrl+C to stop watching
```

#### Sync Xero

```bash
python manage.py start_xero_sync
```

**Expected output:** Error and warning free sync between local and Xero data.

#### Start Celery Beat (Dev)

Beat is the periodic-task dispatcher that keeps Xero tokens refreshed, runs hourly syncs, weekly scraping, and nightly housekeeping. The worker also needs to be running so dispatched tasks actually execute. In separate terminals (each blocks forever):

```bash
poetry run celery -A docketworks worker --concurrency=4 --loglevel=info
poetry run celery -A docketworks beat --loglevel=info --scheduler django_celery_beat.schedulers:DatabaseScheduler
```

#### Verify Celery Beat (Server)

On server instances Beat is already running as a systemd service (`celery-beat-<instance>`), installed by `instance.sh create`. Verify:

```bash
sudo systemctl status celery-beat-<instance>
```

Must show `active (running)`. The Beat startup banner shows the loaded schedule; rows in `/admin/django_celery_results/taskresult/` confirm tasks are actually firing.

#### Run All Validators

```bash
for s in scripts/restore_checks/check_*.py; do python "$s"; done
```

**Expected output:** Each script prints its own success line and exits zero. Covers: Django ORM (`check_django_orm.py`), admin user (`check_admin_user.py`), company defaults (`check_company_defaults.py`), AI providers (`check_ai_providers.py`), JobFiles (`check_jobfiles.py`), shop company (`check_shop_company.py`), test company (`check_test_company.py`), Xero app (`check_xero_app.py`), Xero accounts (`check_xero_accounts.py`), Xero seed (`check_xero_seed.py`).

Any non-zero exit means the upstream mutation step that should have produced that state silently failed — fix the underlying problem, do not re-run just the failing check.

#### Test Serializers

```bash
python scripts/restore_checks/test_serializers.py --verbose
```

**Expected:** `ALL SERIALIZERS PASSED!` or specific failure details if issues found.

#### Test Kanban HTTP API

```bash
python scripts/restore_checks/test_kanban_api.py
```

**Expected output:**

```
API working: 174 active jobs, 23 archived
```

#### Snapshot Verified Database

The DB is now in a known-good state: loaded from prod, migrated, fixtures applied, Xero synced, validators and smoke tests green. Capture this state as a baseline so the Playwright run — or any later test run — can be recovered from it without re-running this entire runbook.

```bash
mkdir -p backups
TS=$(date +%Y%m%d_%H%M%S)
OUT="backups/post_restore_${TS}.sql.gz"

# Atomic write: dump to .tmp, rename on success. pipefail ensures pg_dump
# failure propagates even though gzip would succeed on empty stdin.
set -o pipefail
PGPASSWORD="$DB_PASSWORD" pg_dump -h localhost -U "$DB_USER" "$DB_NAME" \
  | gzip > "$OUT.tmp"
mv "$OUT.tmp" "$OUT"
set +o pipefail

echo "Baseline snapshot: $OUT"
```

**Check:**

```bash
ls -lh backups/post_restore_*.sql.gz | tail -1
# Should show a file >= 5 MB (gzipped full dump).
```

#### Run Playwright Tests

Before E2E, restart the backend, Celery worker, and Celery Beat with
`XERO_READONLY=True`. The user starts these long-running services; the agent
does not. All three processes must use the flag because it is process-scoped.

```bash
cd frontend
PATH="$PWD/../.venv/bin:$PATH" npm run test:e2e
```

Run in the foreground without a shell timeout or SIGTERM. Global teardown must
finish so it can restore the database, preserve/reinject the Xero token, remove
the lock, and run integrity checks. **Expected:** all tests and teardown pass.

## Cleanup

Retain the source dump, `restore/pre_migration_state.json`, and the verified
post-restore snapshot through E2E and release verification. After explicit
operator approval, remove only the named source dump. Never recursively remove
`restore/`; it also contains E2E recovery artifacts.

## Troubleshooting

### Reset Script Fails

**Symptoms:** Permission denied errors
**Solution:** Ensure PostgreSQL is running and you have sudo access: `sudo -u postgres psql -c "\l"`

### E2E Restore Failed / DB Reflects Test Mutations

**Symptoms:** `global-teardown.ts` printed the "E2E TEARDOWN FAILED TO RESTORE DATABASE" banner, or the dev DB contains rows created by Playwright tests.

**Solution:** Restore from the baseline snapshot. Pick the newest file in `backups/`:

```bash
LATEST=$(ls -t backups/post_restore_*.sql.gz | head -1)
echo "Restoring from: $LATEST"

python manage.py dbshell -- -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
gunzip -c "$LATEST" | PGPASSWORD="$DB_PASSWORD" psql \
  -v ON_ERROR_STOP=1 --single-transaction \
  -h localhost -U "$DB_USER" -d "$DB_NAME"
```

`--single-transaction` + `ON_ERROR_STOP=1` mirrors the atomic restore contract used by `global-teardown.ts`: any failure rolls back, leaving the empty schema rather than a half-loaded DB. If restore succeeds, sanity-check with `python scripts/restore_checks/check_django_orm.py`.

## File Locations

- **Scrubbed dump (consumer-side):** `restore/scrubbed_<source-db>_<ts>.dump`
- **Scrubbed dump (producer-side, on prod):** `<BASE_DIR>/restore/scrubbed_<DB_NAME>_<ts>.dump`
- **Pre-migration count artifact:** `restore/pre_migration_state.json`
- **Baseline snapshot:** `backups/post_restore_<TS>.sql.gz`

## First-time setup (existing instances only)

New instances pick up the scrub DB automatically via `scripts/server/instance.sh`.
Existing instances provisioned before this change need one `instance.sh reconfigure`
run.
