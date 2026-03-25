# Production Data Backup and Restore Process

CRITICAL: audit

The finished application will be audited against a log file you must write as you follow the steps.  Every command you run and its key output must be added to this log.

e.g.  logs/restore_log_prod_backup_20260109_211941_complete.log



## PostgreSQL Connection Pattern

ALL psql commands must include: `-h "$DB_HOST" -p "$DB_PORT"`

**Linux/WSL (bash):**
```bash
PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" "$DB_NAME" -c "\dt"
```

**Windows (PowerShell):**
```powershell
$env:PGPASSWORD = $env:DB_PASSWORD
psql.exe -h $env:DB_HOST -p $env:DB_PORT -U $env:DB_USER $env:DB_NAME -c "\dt"
Remove-Item Env:PGPASSWORD
```

## CRITICAL: No Workarounds

This process runs unattended on UAT with no user interaction. Any workaround you apply on dev will fail silently on UAT. If anything goes wrong, STOP and fix the underlying problem.

## Overview/Target State

You should end up with:
1. The backend running on port 8000
2. ngrok mapping a public domain to the backend
3. ngrok mapping a public domain to the frontend
4. The frontend (in its own repo) running on port 5173
5. The database fully deleted, then restored from prod
6. All migrations applied
7. Linked to the dev Xero
8. Key data from prod's restore synced to the dev xero
9. The Xero token is locked in via python manage.py run_scheduler
10. LLM keys set up and configured
11. Playwright tests pass


## CRITICAL ORDER ENFORCEMENT

**NEVER run steps out of order. The following steps MUST be completed before ANY testing:**
1. Steps 1-20: Basic restore and setup
2. Step 21: **XERO OAUTH CONNECTION** (CANNOT BE SKIPPED)
3. Steps 22-27: Xero configuration
4. Steps 28-30: Testing ONLY AFTER Xero is connected

## One-Time Machine Setup (before first restore)

These must be in place before running the process. They persist across restores.

1. **`.env`** — Copy from `.env.example` and configure `MYSQL_DATABASE`, `MYSQL_DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`, and all other required variables.
2. **`apps/workflow/fixtures/ai_providers.json`** — Copy from `ai_providers.json.example` and add real API keys for Claude, Gemini, and Mistral.

## Technical Notes

- Use `--execute="source file.sql"` not `< file.sql` for SQL scripts (large files fail with redirection)

### PRODUCTION STEPS

#### Step 1: Create Backup (Production)

**Run as:** Production system user with Django access
**Command:**

```bash
python manage.py backport_data_backup
```

This creates a zip file in `/tmp` containing both the schema and anonymized data backup.

**Check:**

```bash
ls -la /tmp/prod_backup_*_complete.zip
# Should show zip file (typically 5-25MB)
```

#### Step 2: Transfer Backup to Development

**Command:**

```bash
scp prod-server:/tmp/prod_backup_YYYYMMDD_HHMMSS_complete.zip restore/
```

**Check:**

```bash
ls -la restore/*.zip
# Should show the zip file transferred
```

#### Step 3: Extract Backup Files

**Command:**

```bash
cd restore && unzip prod_backup_YYYYMMDD_HHMMSS_complete.zip
```

**Windows (PowerShell):**

```powershell
Expand-Archive -Path restore\prod_backup_YYYYMMDD_HHMMSS_complete.zip -DestinationPath restore -Force
```

**Check:**

```bash
ls -la restore/
# Should show both .json.gz and .schema.sql files
```

### DEVELOPMENT STEPS

#### Step 4: Verify Environment Configuration

**Check:**

```bash
grep -E "^(DB_NAME|DB_USER|DB_PASSWORD|DB_HOST|DB_PORT)=" .env
export DB_PASSWORD=$(grep DB_PASSWORD .env | cut -d= -f2)
export DB_NAME=$(grep DB_NAME .env | cut -d= -f2)
export DB_USER=$(grep DB_USER .env | cut -d= -f2)
```

**Windows (PowerShell):**

```powershell
Select-String -Path .env -Pattern '^(DB_NAME|DB_USER|DB_PASSWORD|DB_HOST|DB_PORT)='
```

**Must show:**

```
DB_NAME=dw_msm_dev
DB_USER=dw_msm_dev
DB_PASSWORD=your_dev_password
DB_HOST=127.0.0.1
DB_PORT=5432
```

**If any missing:** Add to .env file

Note. If you're using Claude or similar, you need to specify these explicitly on all subsequent command lines rather than use environment variables

#### Step 5: Reset Database

**Command:**

```bash
./scripts/setup_database.sh --drop
```

This drops and recreates the database and user from your `.env` file.

**Windows:** Run from WSL or use pgAdmin to drop/recreate the database.

**Check:**

```bash
PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" "$DB_NAME" -c "\dt"
# Should return: Did not find any relations.
```

#### Step 6: Apply Django Migrations (creates schema)

**Command:**

```bash
python manage.py migrate
```

**Check:**

```bash
PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" "$DB_NAME" -c "\dt" | wc -l
# Should show 50+ tables
```

#### Step 7: Extract JSON Backup

**Commands:**

```bash
# Extract the compressed backup
gunzip restore/prod_backup_YYYYMMDD_HHMMSS.json.gz
```

**Check:**

```bash
ls -la restore/prod_backup_YYYYMMDD_HHMMSS.json
# Should show large file (typically 50-200MB)
```

#### Step 8: Load Production Data

**Command:**

```bash
python manage.py loaddata restore/prod_backup_YYYYMMDD_HHMMSS.json
```

**Check:**

```bash
PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" "$DB_NAME" -c "
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

#### Step 9: Verify Django Migrations

Migrations were already applied in Step 6. Verify they're all applied:

**Command:**

```bash
python manage.py showmigrations | grep '\[ \]'
```

**Expected:** No output (all migrations applied). If any show `[ ]`, run `python manage.py migrate`.

#### Step 10: Load Company Defaults Fixture

**Command:**

```bash
python manage.py loaddata apps/workflow/fixtures/company_defaults.json
```

**Check:**

```bash
python scripts/restore_checks/check_company_defaults.py
```

**Expected output:** `Company defaults loaded: Demo Company`

#### Step 11: Load AI Providers Fixture

**Command:**

```bash
python manage.py loaddata apps/workflow/fixtures/ai_providers.json
```

**Check (validates API keys actually work):**

```bash
python scripts/restore_checks/check_ai_providers.py
```

**Expected output:** Each provider shows a response or "API key valid".

#### Step 12: Verify Specific Data

**Command:**

```bash
PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" "$DB_NAME" -c "
SELECT id, name, job_number, status
FROM workflow_job
WHERE name LIKE '%test%' OR name LIKE '%sample%'
LIMIT 5;
"
```

**Check:** Should show actual job records with realistic data

#### Step 13: Test Django ORM

**Command:**

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

#### Step 14: Set Up Development Logins

**Command:**

```bash
python scripts/setup_dev_logins.py
```

**What this does:**
1. Creates a default admin user (defaultadmin@example.com) if it doesn't exist
2. Resets ALL staff passwords to a default value for development testing

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

#### Step 15: Create Dummy Files for JobFile Instances

**Command:**

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

#### Step 16: Fix Shop Client Name (Required after Production Restore)

**Command:**

```bash
python scripts/restore_checks/fix_shop_client.py
```

**Check:**

```bash
python scripts/restore_checks/check_shop_client.py
```

**Expected output:** `Shop client: Demo Company Shop`
#### Step 17: Verify Test Client Exists or Create if Needed

The test client is used by the test suite. Create it if missing:

```bash
python scripts/restore_checks/check_test_client.py
```

**Expected output:** `Test client already exists: ABC Carpet Cleaning TEST IGNORE ...` or `Created test client: ...`

#### Step 18: Start ngrok Tunnel (skip for UAT)

Note, this is often already running. Check first.

```bash
ngrok http 5173 --domain=your-domain.ngrok-free.app
```

**Check:** The ngrok tunnel should show "Forwarding" status with a public URL. Vite proxies `/api` to Django.

#### Step 19: Start Development Server (skip for UAT)


**Check if server is already running:**

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000
```

**Windows (PowerShell):**

```powershell
curl.exe -s -o $null -w "%{http_code}`n" http://localhost:8000
```

If you get 302, **SKIP this step** - server is already running.

**If curl fails, ask the user to start the server:**

In VS Code: Run menu > Start Debugging (F5)

**Check:** Re-run the curl command above - should return 302.

#### Step 20: Start Frontend (skip for UAT)


**Check if frontend is already running:**

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:5173
```

**Windows (PowerShell):**

```powershell
curl.exe -s -o $null -w "%{http_code}`n" http://localhost:5173
```

If you get 200, **SKIP this step** - frontend is already running.

**If curl fails, start the frontend (in separate terminal):**

```bash
cd frontend && npm run dev
```

**Check:** Re-run the curl command above - should return 200.

#### Step 21: Connect to Xero OAuth

**Command:**

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

#### Step 22: Configure Xero Connection

**Command:**

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

**Note:** Requires `xero_payroll_calendar_name` to be set in CompanyDefaults (loaded from fixture in Step 10).

Brand new install or reset Xero Dev? The payroll calendar won't be found here.
 You must create the missing calendar in Xero (Payroll > Payroll Settings > Payroll Calendars).


#### Step 23: Sync Chart of Accounts from Xero

**Command:**

```bash
python manage.py start_xero_sync --entity accounts
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

#### Step 24: Sync Pay Items from Xero

**Command:**

```bash
python manage.py xero --configure-payroll
```

**Expected output:** `✓ XeroPayItem sync completed!`

#### Step 25: Seed Database to Xero


**WARNING:** This step takes 10+ minutes. Run in background.

**Command:**

```bash
nohup python manage.py seed_xero_from_database > logs/seed_xero_output.log 2>&1 &
echo "Background process started, PID: $!"
```

**Windows (PowerShell):**

```powershell
Start-Process -FilePath python -ArgumentList "manage.py", "seed_xero_from_database" -RedirectStandardOutput logs\seed_xero_output.log -RedirectStandardError logs\seed_xero_output.log
Get-Content logs\seed_xero_output.log -Tail 50 -Wait
```

**What this does:**
1. Clears production Xero IDs (clients, jobs, stock, purchase orders, staff)
2. Remaps XeroPayItem FK references (Job.default_xero_pay_item, CostLine.xero_pay_item) from prod UUIDs to dev UUIDs by matching pay item names
3. Links/creates contacts in Xero for all clients
4. Creates projects in Xero for all jobs
5. Syncs stock items to Xero inventory (using account codes from Step 23)
6. Links/creates payroll employees for all active staff (uses Staff UUID in job_title for reliable re-linking)

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

#### Step 26: Sync Xero

**Command:**

```bash
python manage.py start_xero_sync
```

**Expected output:**

Error and warning free sync between local and xero data.

#### Step 27: Start Background Scheduler

**Command (in separate terminal):**

```bash
python manage.py run_scheduler
```

This keeps the Xero token refreshed automatically.

#### Step 28: Test Serializers

**Command:**

```bash
python scripts/restore_checks/test_serializers.py --verbose
```

**Expected:** `✅ ALL SERIALIZERS PASSED!` or specific failure details if issues found.

#### Step 29: Test Kanban HTTP API

**Command:**

```bash
python scripts/restore_checks/test_kanban_api.py
```

**Expected output:**

```
✓ API working: 174 active jobs, 23 archived
```

#### Step 30: Run Playwright Tests

**Command:**

```bash
cd frontend && npx playwright test
```

**Expected:** All tests pass.

## Troubleshooting

### Reset Script Fails

**Symptoms:** Permission denied errors
**Solution:** Ensure PostgreSQL is running and you have sudo access: `sudo -u postgres psql -c "\l"`

## File Locations

- **Combined backup:** `/tmp/prod_backup_YYYYMMDD_HHMMSS_complete.zip` (created by backup command)
- **Production schema:** `prod_backup_YYYYMMDD_HHMMSS.schema.sql` (inside zip, for reference only)
- **Production data:** `prod_backup_YYYYMMDD_HHMMSS.json.gz` (inside zip)
- **Development restore:** `restore/` directory
- **Setup script:** `scripts/setup_database.sh`

## Required Passwords

- **Production PostgreSQL:** Production database password
- **Development PostgreSQL:** Value from `DB_PASSWORD` in `.env`
- **System sudo:** For running setup script (uses `sudo -u postgres`)
