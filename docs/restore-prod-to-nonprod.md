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
3. Steps 16-21: Xero configuration
4. Steps 22-24: Testing ONLY AFTER Xero is connected

## Prerequisites

- `.env` configured with `DB_NAME`, `DB_USER`, `DB_PASSWORD`, and all other required variables
- `apps/workflow/fixtures/ai_providers.json` — copy from `.json.example` and add real API keys
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
SELECT 'workflow_job' as table_name, COUNT(*) as count FROM workflow_job
UNION ALL SELECT 'accounts_staff', COUNT(*) FROM accounts_staff
UNION ALL SELECT 'client_client', COUNT(*) FROM client_client
UNION ALL SELECT 'job_costset', COUNT(*) FROM job_costset
UNION ALL SELECT 'job_costline', COUNT(*) FROM job_costline;
"
```

**Expected output (approximate):**

```
  table_name   | count
---------------+-------
 workflow_job   |  1054
 accounts_staff |    20
 client_client  |  3739
 job_costset    |  3162
 job_costline   | 10334
```

#### Step 6: Verify Django Migrations

Migrations were already applied in Step 3. Verify they're all applied:

```bash
python manage.py showmigrations | grep '\[ \]'
```

**Expected:** No output (all migrations applied). If any show `[ ]`, run `python manage.py migrate`.

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

#### Step 8: Load AI Providers Fixture

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
FROM workflow_job
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

Brand new install or reset Xero Dev? The payroll calendar won't be found here. You must create the missing calendar in Xero (Payroll > Payroll Settings > Payroll Calendars).

#### Step 17: Sync Chart of Accounts from Xero

```bash
python manage.py start_xero_sync --entity accounts --force
```

**What this does:**
Fetches the chart of accounts from Xero and populates the XeroAccount table with account codes, names, and types. This is required for stock sync to work correctly (needs account codes 200 for Sales and 300 for Purchases).

**Check:**

```bash
python scripts/restore_checks/check_xero_accounts.py
```

**Expected output:**

```
Total accounts synced: ~62
Sales account (200): Sales
Purchases account (300): Purchases
```

#### Step 18: Sync Pay Items from Xero

```bash
python manage.py xero --configure-payroll
```

**Expected output:** `✓ XeroPayItem sync completed!`

#### Step 19: Seed Database to Xero

**WARNING:** This step takes 10+ minutes. Run in background.

```bash
nohup python manage.py seed_xero_from_database > logs/seed_xero_output.log 2>&1 &
echo "Background process started, PID: $!"
```

**What this does:**
1. Clears production Xero IDs (clients, jobs, stock, purchase orders, staff)
2. Remaps XeroPayItem FK references (Job.default_xero_pay_item, CostLine.xero_pay_item) from prod UUIDs to dev UUIDs by matching pay item names
3. Links/creates contacts in Xero for all clients
4. Creates projects in Xero for all jobs
5. Syncs stock items to Xero inventory (using account codes from Step 17)
6. Links/creates payroll employees for all active staff (uses Staff UUID in job_title for reliable re-linking)
7. Sets `enable_xero_sync = True` in CompanyDefaults (Xero sync is blocked until this point)

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

#### Step 20: Sync Xero

```bash
python manage.py start_xero_sync
```

**Expected output:** Error and warning free sync between local and Xero data.

#### Step 21: Start Background Scheduler

```bash
python manage.py run_scheduler
```

This keeps the Xero token refreshed automatically.

#### Step 22: Test Serializers

```bash
python scripts/restore_checks/test_serializers.py --verbose
```

**Expected:** `ALL SERIALIZERS PASSED!` or specific failure details if issues found.

#### Step 23: Test Kanban HTTP API

```bash
python scripts/restore_checks/test_kanban_api.py
```

**Expected output:**

```
API working: 174 active jobs, 23 archived
```

#### Step 24: Run Playwright Tests

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
