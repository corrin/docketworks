# Restore Production to Non-Production

Restore a production backup to any non-production environment (dev or server instance). This guide is environment-agnostic: assume venv active, .env loaded, in the project root. All paths are relative.

CRITICAL: audit

The finished application will be audited against a log file you must write as you follow the steps. Every command you run and its key output must be added to this log.

e.g. `logs/restore_log_prod_backup_20260109_211941_complete.log`

## CRITICAL: No Workarounds

This process runs unattended on server instances with no user interaction. Any workaround you apply will fail silently in automated runs. If anything goes wrong, STOP and fix the underlying problem.

## CRITICAL ORDER ENFORCEMENT

**NEVER run steps out of order. The following steps MUST be completed before ANY testing:**
1. Steps 1-14: Basic restore and setup
2. Step 15: **XERO OAUTH CONNECTION** (CANNOT BE SKIPPED)
3. Steps 16-20: Xero configuration
4. Steps 21-23: Testing ONLY AFTER Xero is connected

## Prerequisites

- `.env` configured with `DB_NAME`, `DB_USER`, `DB_PASSWORD`, and all other required variables
- A production backup zip in `restore/`, extracted:
  ```bash
  # On production: python manage.py backport_data_backup
  # Then transfer and extract:
  scp prod-server:/tmp/prod_backup_YYYYMMDD_HHMMSS_complete.zip restore/
  cd restore && unzip prod_backup_YYYYMMDD_HHMMSS_complete.zip && cd ..
  ```
  You should have `restore/prod_backup_YYYYMMDD_HHMMSS.json.gz` and `restore/prod_backup_YYYYMMDD_HHMMSS.schema.sql`.

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
```

**TEMPORARY HACK — REMOVE BY 2026-05-01, or immediately once the `feat/jobevent-audit` PR is deployed to prod and the next prod backup has been taken from post-0079 data.**

Rewind the `job` app to before the JobEvent.staff_id backfill/NOT-NULL pair. `0078` backfills `JobEvent.staff_id` from `job_historicaljob` and deletes unattributable rows; `0079` then makes `staff_id` NOT NULL. Both need real prod rows in the table to do their work — backups taken from prod before 0078 deploys still contain `staff: null` JobEvent rows, so we load under the pre-0078 schema and migrate forward again in Step 6. Once prod is on ≥0079 and a fresh backup has been taken from there, every new backup already satisfies the constraint and these two extra lines can be deleted.

```bash
python manage.py migrate job 0077
```

**Check:**

```bash
python manage.py showmigrations job | grep -E '007[789]'
# Expect:
#  [X] 0077_backfill_jobevent_detail
#  [ ] 0078_backfill_jobevent_staff_from_history
#  [ ] 0079_alter_jobevent_staff_not_null
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

#### Step 6: Re-apply Migrations That Were Rewound in Step 3

Step 3 rewound `job` to `0077` so `loaddata` could insert the pre-0078 prod rows. Now run `migrate` again: `0078` will backfill `JobEvent.staff_id` from `job_historicaljob` (joining within ±1 minute of each event) and delete the small number of events that have no attributable `history_user_id`, and `0079` will reinstate `NOT NULL` on `staff_id`.

```bash
python manage.py migrate
```

**Check:**

```bash
python manage.py showmigrations | grep '\[ \]'
# Expect no output.

PGPASSWORD="$DB_PASSWORD" psql -U "$DB_USER" "$DB_NAME" -c \
  "SELECT COUNT(*) FROM job_jobevent WHERE staff_id IS NULL;"
# Expect: 0
```

Once the `feat/jobevent-audit` PR is in prod and a post-0079 backup exists, drop the `migrate job 0077` line from Step 3 and collapse this step back to a plain "verify all migrations applied" check — the rewind/replay dance is only needed while prod backups still contain `staff: null` JobEvent rows.

#### Step 7: Load Company Defaults Fixture

This replaces your real company name with a demo/dummy value

```bash
python manage.py loaddata apps/workflow/fixtures/company_defaults.json
```

**Check:**

```bash
python scripts/restore_checks/check_company_defaults.py
```

**Expected output:** `Company defaults loaded: Demo Company`

#### Step 8: Reload AI Providers

The DB reset wiped the AI provider rows. Reload from the fixture generated during instance creation:

```bash
python manage.py loaddata apps/workflow/fixtures/ai_providers.json
```

**Check (validates API keys actually work):**

```bash
python scripts/restore_checks/check_ai_providers.py
```

**Expected output:** Each provider shows a response or "API key valid".

#### Step 9: Verify Specific Data

```bash
PGPASSWORD="$DB_PASSWORD" psql -U "$DB_USER" "$DB_NAME" -c "
SELECT id, name, job_number, status
FROM job_job
WHERE name LIKE '%test%' OR name LIKE '%sample%'
LIMIT 5;
"
```

**Check:** Should show actual job records with realistic data.

#### Step 10: Test Django ORM

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

#### Step 11: Set Up Development Logins

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

#### Step 12: Create Dummy Files for JobFile Instances

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

#### Step 13: Fix Shop Client Name

```bash
python scripts/restore_checks/fix_shop_client.py
```

**Check:**

```bash
python scripts/restore_checks/check_shop_client.py
```

**Expected output:** `Shop client: Demo Company Shop`

#### Step 14: Verify Test Client

```bash
python scripts/restore_checks/check_test_client.py
```

**Expected output:** `Test client already exists: ABC Carpet Cleaning TEST IGNORE ...` or `Created test client: ...`

#### Step 15: Connect to Xero OAuth

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

#### Step 16: Configure Xero Connection

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

**Note:** Requires `xero_payroll_calendar_name` to be set in CompanyDefaults (loaded from fixture in Step 7).

If the payroll calendar is missing (e.g. after a Xero demo org reset), re-run with:

```bash
python manage.py xero --setup --create-missing-xero-items
```

#### Step 17: Sync Pay Items from Xero

```bash
python manage.py xero --configure-payroll
```

**Expected output:** `✓ XeroPayItem sync completed!`

#### Step 18: Seed Database to Xero

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

#### Step 19: Sync Xero

```bash
python manage.py start_xero_sync
```

**Expected output:** Error and warning free sync between local and Xero data.

#### Step 20a (Dev): Start Background Scheduler

The scheduler is a separate process that keeps Xero tokens refreshed, runs hourly syncs, weekly scraping, and nightly housekeeping. In a separate terminal (it blocks forever):

```bash
python manage.py run_scheduler
```

#### Step 20b (Server): Verify Background Scheduler

On server instances the scheduler is already running as a systemd service (`scheduler-<instance>`), installed by `instance.sh create`. Verify:

```bash
sudo systemctl status scheduler-<instance>
```

Must show `active (running)`. The "registered jobs" lines in Django startup logs are just declarations -- they do not mean jobs are executing.

#### Step 21: Test Serializers

```bash
python scripts/restore_checks/test_serializers.py --verbose
```

**Expected:** `ALL SERIALIZERS PASSED!` or specific failure details if issues found.

#### Step 22: Test Kanban HTTP API

```bash
python scripts/restore_checks/test_kanban_api.py
```

**Expected output:**

```
API working: 174 active jobs, 23 archived
```

#### Step 23: Run Playwright Tests

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

## File Locations

- **Combined backup:** `/tmp/prod_backup_YYYYMMDD_HHMMSS_complete.zip` (created by backup command)
- **Production schema:** `prod_backup_YYYYMMDD_HHMMSS.schema.sql` (inside zip, for reference only)
- **Production data:** `prod_backup_YYYYMMDD_HHMMSS.json.gz` (inside zip)
- **Restore directory:** `restore/`
