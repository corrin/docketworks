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
grep -E "^(DB_NAME|DB_USER|DB_PASSWORD)=" .env
export DB_PASSWORD=$(grep DB_PASSWORD .env | cut -d= -f2)
export DB_NAME=$(grep DB_NAME .env | cut -d= -f2)
export DB_USER=$(grep DB_USER .env | cut -d= -f2)
```

**Must show:**

```
DB_NAME=dw_<client>_<env>
DB_USER=dw_<client>_<env>
DB_PASSWORD=your_password
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
  ./restore/scrubbed_<DB_NAME>_<ts>.dump
```

**Check:**

```bash
PGPASSWORD="$DB_PASSWORD" psql -U "$DB_USER" "$DB_NAME" -c "
SELECT 'job_job' as table_name, COUNT(*) as count FROM job_job
UNION ALL SELECT 'accounts_staff', COUNT(*) FROM accounts_staff
UNION ALL SELECT 'client_client', COUNT(*) FROM client_client
UNION ALL SELECT 'job_costset', COUNT(*) FROM job_costset
UNION ALL SELECT 'job_costline', COUNT(*) FROM job_costline;
"
```

**Expected output (approximate):**

```
  table_name    | count
----------------+-------
 job_job         |  1054
 accounts_staff  |    20
 client_client   |  3739
 job_costset     |  3162
 job_costline    | 10334
```

Then smoke-test the Django ORM against the restored data — fail fast here rather than letting a broken ORM surface later in the validator loop:

```bash
python scripts/restore_checks/check_django_orm.py
```

**Expected output:**

```
Jobs: ~1400
Staff: ~22
Clients: ~4800
Sample job: [any real job name] (#XXXXX)
Contact: [any real contact name]
```

#### Apply Django Migrations

`django_migrations` rode along in the dump, so this only runs migrations the dev branch has beyond prod's state. On a fresh prod-aligned checkout it's a no-op.

```bash
python manage.py migrate
```

**Check:**

```bash
python manage.py showmigrations | grep '\[ \]'
# Expect no output.
```

#### Load Company Defaults Fixture

This replaces your real company name and logos with the shipped DocketWorks
demo values. The fixture references logos at `app_images/...` under
`MEDIA_ROOT`; the PNGs are committed in `mediafiles/app_images/` and resolve
directly, no copy step.

```bash
python manage.py loaddata apps/workflow/fixtures/company_defaults.json
```

#### Reload AI Providers

The DB reset wiped the AI provider rows. Reload from the fixture generated during instance creation:

```bash
python manage.py loaddata apps/workflow/fixtures/ai_providers.json
```

#### Reload Xero App Credentials

Prod's Xero app credentials are scrubbed from the dump (`db_scrubber._EXCLUDED_TABLES` truncates `workflow_xeroapp` before pg_dump). Load this install's own credentials from the per-install fixture:

```bash
python manage.py loaddata apps/workflow/fixtures/xero_apps.json
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

#### Fix Shop Client Name

```bash
python scripts/restore_checks/fix_shop_client.py
```

#### Create Test Client

Creates the test client named per `CompanyDefaults.test_client_name` (e.g. `ABC Carpet Cleaning TEST IGNORE`) if it isn't already there. Idempotent. Required by Seed Database to Xero, which crashes if the client is missing.

```bash
python scripts/fix_test_client.py
```

**Expected output:** `Test client already exists: …` or `Created test client: …`.

#### Connect to Xero OAuth

**Dev only:** Before this step, start ngrok, the backend, and the frontend — see [development_session.md](development_session.md).

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

If the payroll calendar is missing (e.g. after a Xero demo org reset), re-run with:

```bash
python manage.py xero --setup --create-missing-xero-items
```

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
1. Clears production Xero IDs (clients, jobs, stock, purchase orders, staff)
2. Updates XeroAccount xero_ids from prod to dev Xero tenant (fetches from dev Xero, upserts by account_name)
3. Remaps XeroPayItem FK references (Job.default_xero_pay_item, CostLine.xero_pay_item) from prod UUIDs to dev UUIDs by matching pay item names
4. Links/creates contacts in Xero for all clients
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

**Expected output:** Each script prints its own success line and exits zero. Covers: Django ORM (`check_django_orm.py`), admin user (`check_admin_user.py`), company defaults (`check_company_defaults.py`), AI providers (`check_ai_providers.py`), JobFiles (`check_jobfiles.py`), shop client (`check_shop_client.py`), test client (`check_test_client.py`), Xero app (`check_xero_app.py`), Xero accounts (`check_xero_accounts.py`), Xero seed (`check_xero_seed.py`).

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

```bash
cd frontend && npx playwright test
```

**Expected:** All tests pass.

## Cleanup

```bash
rm -rf restore/
```

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

- **Scrubbed dump (consumer-side):** `restore/scrubbed_<DB_NAME>_<ts>.dump`
- **Scrubbed dump (producer-side, on prod):** `<BASE_DIR>/restore/scrubbed_<DB_NAME>_<ts>.dump`
- **Baseline snapshot:** `backups/post_restore_<TS>.sql.gz`

## First-time setup (existing instances only)

New instances pick up the scrub DB automatically via `scripts/server/instance.sh`. Existing instances provisioned before this change need a one-off `instance.sh create` re-run (idempotent — adds the scrub DB, skips anything that already exists).
