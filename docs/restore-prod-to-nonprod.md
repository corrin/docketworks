# Restore Production to Non-Production

Restore a production backup to any non-production environment (dev or server instance). This guide is environment-agnostic: assume venv active, .env loaded, in the project root. All paths are relative.

CRITICAL: audit

The finished application will be audited against a log file you must write as you follow the steps. Every command you run and its key output must be added to this log.

e.g. `logs/restore_log_prod_backup_20260109_211941_complete.log`

## CRITICAL: No Workarounds

This process runs unattended on server instances with no user interaction. Any workaround you apply will fail silently in automated runs. If anything goes wrong, STOP and fix the underlying problem.

## CRITICAL ORDER ENFORCEMENT

**NEVER run steps out of order. The following steps MUST be completed before ANY testing:**
1. Steps 1-13: Basic restore and setup
2. Step 14: **XERO OAUTH CONNECTION** (CANNOT BE SKIPPED)
3. Steps 15-19: Xero configuration
4. Steps 20-22: Testing ONLY AFTER Xero is connected

## Prerequisites

- `.env` configured with `DB_NAME`, `DB_USER`, `DB_PASSWORD`, and all other required variables
- A production backup zip in `restore/`, extracted:
  ```bash
  # On production: python manage.py backport_data_backup
  # Then transfer and extract:
  scp prod-server:/tmp/prod_backup_YYYYMMDD_HHMMSS_complete.zip restore/
  cd restore && unzip prod_backup_YYYYMMDD_HHMMSS_complete.zip && cd ..
  ```
  You should have `restore/prod_backup_YYYYMMDD_HHMMSS.json.gz` and `restore/prod_backup_YYYYMMDD_HHMMSS.schema.sql`. Newer backups also include `prod_backup_YYYYMMDD_HHMMSS.migrations.json`; it is not used by the default flow.

---

#### Step 1: Verify Environment Configuration

**Check:**

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

#### Step 2: Reset Database

Drop all tables by dropping and recreating the public schema:

```bash
python manage.py dbshell -- -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
```

**Check:**

```bash
python manage.py dbshell -- -c "\dt"
# Should return: Did not find any relations.
```

#### Step 3: Apply Django Migrations

```bash
python manage.py migrate
```

**Check:**

```bash
PGPASSWORD="$DB_PASSWORD" psql -U "$DB_USER" "$DB_NAME" -c "\dt" | wc -l
# Should show 50+ tables

python manage.py showmigrations | grep '\[ \]'
# Expect no output.
```

#### Step 4: Extract JSON Backup

```bash
gunzip restore/prod_backup_YYYYMMDD_HHMMSS.json.gz
```

**Check:**

```bash
ls -la restore/prod_backup_YYYYMMDD_HHMMSS.json
# Should show large file (typically 50-200MB)
```

#### Step 5: Load Production Data

```bash
python manage.py loaddata restore/prod_backup_YYYYMMDD_HHMMSS.json
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

#### Step 6: Load Company Defaults Fixture

This replaces your real company name and logos with the shipped DocketWorks
demo values. The fixture references logos at `app_images/...` under
`MEDIA_ROOT`; the PNGs are committed in `mediafiles/app_images/` and resolve
directly, no copy step.

```bash
python manage.py loaddata apps/workflow/fixtures/company_defaults.json
```

**Check:**

```bash
python scripts/restore_checks/check_company_defaults.py
```

**Expected output:**

```
Company defaults loaded: Demo Company
logo_wide: app_images/docketworks_logo_wide.png
```

#### Step 7: Reload AI Providers

The DB reset wiped the AI provider rows. Reload from the fixture generated during instance creation:

```bash
python manage.py loaddata apps/workflow/fixtures/ai_providers.json
```

**Check (validates API keys actually work):**

```bash
python scripts/restore_checks/check_ai_providers.py
```

**Expected output:** Each provider shows a response or "API key valid".

#### Step 8: Verify Specific Data

```bash
PGPASSWORD="$DB_PASSWORD" psql -U "$DB_USER" "$DB_NAME" -c "
SELECT id, name, job_number, status
FROM job_job
WHERE name LIKE '%test%' OR name LIKE '%sample%'
LIMIT 5;
"
```

**Check:** Should show actual job records with realistic data.

#### Step 9: Test Django ORM

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

#### Step 10: Set Up Development Logins

```bash
python scripts/setup_dev_logins.py
```

Creates a default admin user and resets all staff passwords to defaults.

**Check:**

```bash
python scripts/restore_checks/check_admin_user.py
```

**Expected output:**

```
User exists: defaultadmin@example.com
Is active: True
Is office staff: True
Is superuser: True
```

**Login credentials after restore:**
- Admin: `defaultadmin@example.com` / `Default-admin-password`
- All other staff: their email / `Default-staff-password`

#### Step 11: Create Dummy Files for JobFile Instances

```bash
python scripts/recreate_jobfiles.py
```

**Check:**

```bash
python scripts/restore_checks/check_jobfiles.py
```

**Expected output:**

```
Total JobFile records with file_path: ~3000
Dummy files created: ~3000
Missing files: 0
```

#### Step 12: Fix Shop Client Name

```bash
python scripts/restore_checks/fix_shop_client.py
```

**Check:**

```bash
python scripts/restore_checks/check_shop_client.py
```

**Expected output:** `Shop client: Demo Company Shop`

#### Step 13: Verify Test Client

```bash
python scripts/restore_checks/check_test_client.py
```

**Expected output:** `Test client already exists: ABC Carpet Cleaning TEST IGNORE ...` or `Created test client: ...`

#### Step 14: Connect to Xero OAuth

**Dev only:** Before this step, start ngrok, the backend, and the frontend — see [development_session.md](development_session.md).

```bash
cd frontend && npx tsx tests/scripts/xero-login.ts && cd ..
```

**What this does:**
This script automates the Xero OAuth login flow using Playwright. It navigates to the frontend, logs in with the default admin credentials, and completes the Xero OAuth authorization.

**Check:**

```bash
python scripts/restore_checks/check_xero_token.py
```

**Expected output:** `Xero OAuth token found.`

#### Step 15: Configure Xero Connection

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

**Note:** Requires `xero_payroll_calendar_name` to be set in CompanyDefaults (loaded from fixture in Step 6).

If the payroll calendar is missing (e.g. after a Xero demo org reset), re-run with:

```bash
python manage.py xero --setup --create-missing-xero-items
```

#### Step 16: Sync Pay Items from Xero

```bash
python manage.py xero --configure-payroll
```

**Expected output:** `✓ XeroPayItem sync completed!`

#### Step 17: Seed Database to Xero

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

**Check completion:**

```bash
python scripts/restore_checks/check_xero_seed.py
```

**Expected output:**

```
Clients linked to Xero: ~550
Jobs linked to Xero: 0
Stock items synced to Xero: ~440
Staff linked to Xero Payroll: ~15
```

#### Step 18: Sync Xero

```bash
python manage.py start_xero_sync
```

**Expected output:** Error and warning free sync between local and Xero data.

#### Step 19a (Dev): Start Background Scheduler

The scheduler is a separate process that keeps Xero tokens refreshed, runs hourly syncs, weekly scraping, and nightly housekeeping. In a separate terminal (it blocks forever):

```bash
python manage.py run_scheduler
```

#### Step 19b (Server): Verify Background Scheduler

On server instances the scheduler is already running as a systemd service (`scheduler-<instance>`), installed by `instance.sh create`. Verify:

```bash
sudo systemctl status scheduler-<instance>
```

Must show `active (running)`. The "registered jobs" lines in Django startup logs are just declarations -- they do not mean jobs are executing.

#### Step 20: Test Serializers

```bash
python scripts/restore_checks/test_serializers.py --verbose
```

**Expected:** `ALL SERIALIZERS PASSED!` or specific failure details if issues found.

#### Step 21: Test Kanban HTTP API

```bash
python scripts/restore_checks/test_kanban_api.py
```

**Expected output:**

```
API working: 174 active jobs, 23 archived
```

#### Step 22: Run Playwright Tests

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

### `loaddata` fails with `NOT NULL` violation on `job_jobevent.staff_id`

**Symptoms:** Step 5 fails part-way through with `IntegrityError: null value in column "staff_id" of relation "job_jobevent" violates not-null constraint`.

**Solution:** The backup was taken before the `feat/jobevent-audit` branch (migrations `job.0078`/`0079`) reached prod, so the JSON contains `JobEvent` rows with `staff_id=null`. See [restore-workaround-jobevent-staff-null.md](restore-workaround-jobevent-staff-null.md) for the rewind-and-replay recipe. Once a post-0079 backup has been produced on prod, the default flow works unchanged and that workaround doc can be deleted.

### `loaddata` fails with `UndefinedColumn` on a CompanyDefaults or JobEvent field

**Symptoms:** Step 5 fails immediately with `psycopg.errors.UndefinedColumn: column "<name>" of relation "<table>" does not exist`.

**Cause:** The local branch has added a column that's not yet on prod, and Step 3's `migrate` was run against an earlier checkout of the tree. Rerun Step 3 on the current branch and retry Step 5.

## File Locations

- **Combined backup:** `/tmp/prod_backup_YYYYMMDD_HHMMSS_complete.zip` (created by backup command)
- **Production schema:** `prod_backup_YYYYMMDD_HHMMSS.schema.sql` (inside zip, for reference only)
- **Production data:** `prod_backup_YYYYMMDD_HHMMSS.json.gz` (inside zip)
- **Restore directory:** `restore/`
