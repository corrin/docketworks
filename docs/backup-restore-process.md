# Production Data Backup and Restore Process

CRITICAL: audit

The finished application will be audited against a log file you must write as you follow the steps.  Every command you run and its key output must be added to this log.

e.g.  logs/restore_log_prod_backup_20260109_211941_complete.log



## MySQL Connection Pattern

ALL MySQL commands must include: `-h "$DB_HOST" -P "$DB_PORT"`

**Linux/WSL (bash):**
```bash
MYSQL_PWD="$DB_PASSWORD" mysql -h "$DB_HOST" -P "$DB_PORT" -u "$MYSQL_DB_USER" "$MYSQL_DATABASE" -e "SHOW TABLES;"
```

**Windows (PowerShell):**
```powershell
$env:MYSQL_PWD = $env:DB_PASSWORD
mysql.exe -h $env:DB_HOST -P $env:DB_PORT -u $env:MYSQL_DB_USER $env:MYSQL_DATABASE -e "SHOW TABLES;"
Remove-Item Env:MYSQL_PWD
```

Note: On Windows, always use `--execute "source path\to\file.sql"` for loading SQL files, and remove MYSQL_PWD after each command.

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
grep -E "^(MYSQL_DATABASE|MYSQL_DB_USER|DB_PASSWORD|DB_HOST|DB_PORT)=" .env
export DB_PASSWORD=$(grep DB_PASSWORD .env | cut -d= -f2)
export MYSQL_DATABASE=$(grep MYSQL_DATABASE .env | cut -d= -f2)
export MYSQL_DB_USER=$(grep MYSQL_DB_USER .env | cut -d= -f2)
```

**Windows (PowerShell):**

```powershell
Select-String -Path .env -Pattern '^(MYSQL_DATABASE|MYSQL_DB_USER|DB_PASSWORD|DB_HOST|DB_PORT)='
```

**Must show:**

```
MYSQL_DATABASE=msm_workflow
MYSQL_DB_USER=django_user
DB_PASSWORD=your_dev_password
DB_HOST=localhost
DB_PORT=3306
```

**If any missing:** Add to .env file

Note. If you're using Claude or similar, you need to specify these explicitly on all subsequent command lines rather than use environment variables

#### Step 5: Reset Database

**Run as:** System root (for MySQL admin operations)
**Command:**

```bash
sudo mysql -u root --execute="source scripts/reset_database.sql"
```

**Windows (PowerShell):**

```powershell
$env:MYSQL_PWD = '<mysql_root_password_if_needed>'
mysql.exe -u root --execute="source scripts/reset_database.sql"
Remove-Item Env:MYSQL_PWD
```

**Note:** Adjust for your MySQL setup - add password (`MYSQL_PWD=password`), host (`-h host`), or port (`-P port`) as needed.

**Check:**

```bash
export MYSQL_PWD="$DB_PASSWORD" && mysql -h "$DB_HOST" -P "$DB_PORT" -u "$MYSQL_DB_USER" "$MYSQL_DATABASE" -e "SHOW TABLES;"
# Should return: Empty set (0.00 sec)
export MYSQL_PWD="$DB_PASSWORD" && mysql -h "$DB_HOST" -P "$DB_PORT" -u "$MYSQL_DB_USER" -e "SHOW DATABASES;" | grep "$MYSQL_DATABASE"
# Should show: msm_workflow
```

#### Step 6: Apply Production Schema

**Command:**

```bash
export MYSQL_PWD="$DB_PASSWORD" && mysql -h "$DB_HOST" -P "$DB_PORT" -u "$MYSQL_DB_USER" "$MYSQL_DATABASE" --execute="source restore/prod_backup_YYYYMMDD_HHMMSS.schema.sql"
```

**Check:**

```bash
MYSQL_PWD="$DB_PASSWORD" mysql -h "$DB_HOST" -P "$DB_PORT" -u "$MYSQL_DB_USER" "$MYSQL_DATABASE" -e "SHOW TABLES;" | wc -l
# Should show 50+ tables
MYSQL_PWD="$DB_PASSWORD" mysql -h "$DB_HOST" -P "$DB_PORT" -u "$MYSQL_DB_USER" "$MYSQL_DATABASE" -e "DESCRIBE workflow_job;" | grep contact_person
# Should show: contact_person	varchar(100)	YES		NULL
MYSQL_PWD="$DB_PASSWORD" mysql -h "$DB_HOST" -P "$DB_PORT" -u "$MYSQL_DB_USER" "$MYSQL_DATABASE" -e "SELECT COUNT(*) FROM workflow_job;"
# Should show: 0 (empty table)
```

#### Step 7: Extract and Convert JSON to SQL

**Commands:**

```bash
# Extract the compressed backup
gunzip restore/prod_backup_YYYYMMDD_HHMMSS.json.gz
# Convert to SQL (automatically generates .sql from .json filename)
python scripts/json_to_mysql.py restore/prod_backup_YYYYMMDD_HHMMSS.json
```

**Windows (PowerShell):**

```powershell
python - <<'PY'
import gzip, shutil, pathlib
src = pathlib.Path("restore/prod_backup_YYYYMMDD_HHMMSS.json.gz")
dst = src.with_suffix("")
with gzip.open(src, "rb") as f_in, open(dst, "wb") as f_out:
    shutil.copyfileobj(f_in, f_out)
PY
python scripts/json_to_mysql.py restore\prod_backup_YYYYMMDD_HHMMSS.json
```

**Check:**

```bash
ls -la restore/prod_backup_YYYYMMDD_HHMMSS.sql
# Should show large file (typically 50-200MB)
head -10 restore/prod_backup_YYYYMMDD_HHMMSS.sql
# Should show:
# -- MySQL dump converted from Django JSON backup
# USE msm_workflow;
# SET FOREIGN_KEY_CHECKS=0;
# INSERT INTO `workflow_job` (`id`, `name`, `client_id`...
grep "INSERT INTO" restore/prod_backup_YYYYMMDD_HHMMSS.sql | wc -l
# Should show thousands of INSERT statements
```

#### Step 8: Load Production Data

**Command:**

```bash
MYSQL_PWD="$DB_PASSWORD" mysql -h "$DB_HOST" -P "$DB_PORT" -u "$MYSQL_DB_USER" "$MYSQL_DATABASE" --execute="source restore/prod_backup_YYYYMMDD_HHMMSS.sql"
```

**Windows (PowerShell):**

```powershell
$env:MYSQL_PWD = $env:DB_PASSWORD
mysql.exe -h $env:DB_HOST -P $env:DB_PORT -u $env:MYSQL_DB_USER $env:MYSQL_DATABASE --execute="source restore\\prod_backup_YYYYMMDD_HHMMSS.sql"
Remove-Item Env:MYSQL_PWD
```

**Check:**

```bash
MYSQL_PWD="$DB_PASSWORD" mysql -h "$DB_HOST" -P "$DB_PORT" -u "$MYSQL_DB_USER" "$MYSQL_DATABASE" -e "
SELECT 'workflow_job' as table_name, COUNT(*) as count FROM workflow_job
UNION SELECT 'workflow_staff', COUNT(*) FROM workflow_staff
UNION SELECT 'workflow_client', COUNT(*) FROM workflow_client
UNION SELECT 'job_costset', COUNT(*) FROM job_costset
UNION SELECT 'job_costline', COUNT(*) FROM job_costline
UNION SELECT 'process_form', COUNT(*) FROM process_form
UNION SELECT 'process_form_entry', COUNT(*) FROM process_form_entry
UNION SELECT 'process_procedure', COUNT(*) FROM process_procedure;
"
```

**Expected output (update with actual numbers):**

```
+---------------------+-------+
| table_name          | count |
+---------------------+-------+
| workflow_job        |  1054 |
| workflow_staff      |    20 |
| workflow_client     |  3739 |
| job_costset         |  3162 |
| job_costline        | 10334 |
| process_form        |     5 |
| process_form_entry  |   100 |
| process_procedure   |    20 |
+---------------------+-------+
```

#### Step 9: Apply Django Migrations

**Command:**

```bash
python manage.py migrate
```

**Check:**

```bash
python manage.py showmigrations
```

**Expected:** All migrations should show [X] (applied)

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

#### Step 11: Load AI Providers Fixture (Optional)


**Prerequisite:** Copy `apps/workflow/fixtures/ai_providers.json.example` to `ai_providers.json` and add your real API keys.

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
MYSQL_PWD="$DB_PASSWORD" mysql -h "$DB_HOST" -P "$DB_PORT" -u "$MYSQL_DB_USER" "$MYSQL_DATABASE" -e "
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

#### Step 18: Start ngrok Tunnels (skip for UAT)

**Commands (run in separate terminals):**

Note, these are often already running.  Check first.

```bash
# Terminal 1: ngrok for backend (replace with your domain)
ngrok http 8000 --domain=your-backend.ngrok-free.app

# Terminal 2: ngrok for frontend (replace with your domain)
ngrok http 5173 --domain=your-frontend.ngrok-free.app
```

**Windows (PowerShell):** same commands as above.

**Check:** Both ngrok tunnels should show "Forwarding" status with public URLs.

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
cd ../jobs_manager_front && npm run dev
```

**Check:** Re-run the curl command above - should return 200.

#### Step 21: Connect to Xero OAuth

**Command:**

```bash
pushd ../jobs_manager_front && npx tsx tests/scripts/xero-login.ts && popd
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
cd ../jobs_manager_front && npx playwright test
```

**Expected:** All tests pass.

## Troubleshooting

### Reset Script Fails

**Symptoms:** Permission denied errors
**Solution:** run the create database as root: `sudo mysql --execute="source scripts/reset_database.sql"`

## File Locations

- **Combined backup:** `/tmp/prod_backup_YYYYMMDD_HHMMSS_complete.zip` (created by backup command)
- **Production schema:** `prod_backup_YYYYMMDD_HHMMSS.schema.sql` (inside zip)
- **Production data:** `prod_backup_YYYYMMDD_HHMMSS.json.gz` (inside zip)
- **Development restore:** `restore/` directory
- **Reset script:** `scripts/reset_database.sql`
- **Converter script:** `scripts/json_to_mysql.py`
- **Generated SQL:** `restore/prod_backup_YYYYMMDD_HHMMSS.sql` (auto-generated from JSON)

## Required Passwords

- **Production MySQL:** Production database password
- **Development MySQL:** Value from `DB_PASSWORD` in `.env`
- **System sudo:** For running reset script as MySQL root
