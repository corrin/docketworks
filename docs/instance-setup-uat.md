# Instance Setup: UAT / Test (Backup Restore)

Set up a test instance using production data. The instance connects to Xero Demo Company, not the client's real Xero.

For restoring to **local dev** instead, see [restore-to-dev.md](restore-to-dev.md).

## Prerequisites

- The server admin has already run `instance.sh create` — your instance exists with a database, .env, gunicorn, and nginx config.
- You have SSH access as the instance user (e.g. `dw-msm-uat`).
- A production backup zip file is in your home directory (`~/prod_backup_*_complete.zip`), either SCP'd from production or placed there by the server admin.

## On Login

Your `.bash_profile` auto-activates the venv, loads `.env`, and cd's to the code directory. Verify:

```bash
which python    # should show the venv python
echo $DB_NAME   # should show your database name
pwd              # should be ~/code
```

If not set up, do it manually:

```bash
source ~/.venv/bin/activate
set -a && source ~/.env && set +a
cd ~/code
```

---

## Step 1: Extract Backup

```bash
unzip ~/prod_backup_*_complete.zip -d ~/
gunzip ~/prod_backup_*.json.gz
```

**Check:**
```bash
ls -la ~/prod_backup_*.json
# Should show a large file (typically 50-200MB)
```

## Step 2: Reset Database

Drop all tables by dropping and recreating the public schema:

```bash
python manage.py dbshell -- -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
```

**Check:**
```bash
python manage.py dbshell -- -c "\dt"
```
Expected: `Did not find any relations.`

## Step 3: Apply Migrations

```bash
python manage.py migrate
```

**Check:**
```bash
python manage.py dbshell -- -c "\dt" | wc -l
```
Expected: 50+ tables.

## Step 4: Load Production Data

```bash
python manage.py loaddata ~/prod_backup_*.json
```

**Check:**
```bash
python scripts/restore_checks/check_django_orm.py
```
Expected: Jobs ~1000+, Staff ~20, Clients ~3000+

## Step 5: Load Fixtures

```bash
# Company defaults (overrides prod values with demo settings)
python manage.py loaddata apps/workflow/fixtures/company_defaults.json

# AI providers
python manage.py loaddata apps/workflow/fixtures/ai_providers.json
```

**Check:**
```bash
python scripts/restore_checks/check_company_defaults.py
```
Expected: `Company defaults loaded: Demo Company`

## Step 6: Reset Passwords

```bash
python scripts/setup_dev_logins.py
```

Creates admin user and resets all staff passwords to defaults.

**Check:**
```bash
python scripts/restore_checks/check_admin_user.py
```
Expected: `User exists: defaultadmin@example.com`, `Is superuser: True`

**Login credentials after restore:**
- Admin: `defaultadmin@example.com` / `Default-admin-password`
- All other staff: their email / `Default-staff-password`

## Step 7: Create Dummy Job Files

Production file attachments aren't included in the backup. Create placeholder files so the app doesn't error:

```bash
python scripts/recreate_jobfiles.py
```

**Check:**
```bash
python scripts/restore_checks/check_jobfiles.py
```
Expected: `Missing files: 0`

## Step 8: Fix Shop Client Name

The restored data has the production shop client name. Reset it to match the demo CompanyDefaults:

```bash
python scripts/restore_checks/fix_shop_client.py
```

**Check:**
```bash
python scripts/restore_checks/check_shop_client.py
```
Expected: `Shop client: Demo Company Shop`

## Step 9: Verify Test Client

```bash
python scripts/restore_checks/check_test_client.py
```
Expected: `Test client already exists: ABC Carpet Cleaning TEST IGNORE ...` or creates it.

## Step 10: Connect to Xero (Demo Company)

```bash
cd frontend && npx tsx tests/scripts/xero-login.ts && cd ..
```

This runs Playwright headless to automate the Xero OAuth flow against the Demo Company.

**Check:**
```bash
python scripts/restore_checks/check_xero_token.py
```
Expected: `Xero OAuth token found.`

## Step 11: Configure Xero

```bash
python manage.py xero --setup
```

Sets xero_tenant_id, xero_shortcode, and xero_payroll_calendar_id.

**Note:** Requires a payroll calendar named "Weekly Testing" in Xero Demo Company. Create it in Xero if missing: Payroll > Settings > Payroll Calendars.

## Step 12: Sync Xero Data

```bash
# Chart of accounts
python manage.py start_xero_sync --entity accounts --force

# Pay items
python manage.py xero --configure-payroll
```

**Check:**
```bash
python scripts/restore_checks/check_xero_accounts.py
```
Expected: `Total accounts synced: ~60+`

## Step 13: Seed Xero from Database

**WARNING:** Takes 10+ minutes.

```bash
nohup python manage.py seed_xero_from_database > ~/logs/seed_xero_output.log 2>&1 &
```

This clears production Xero IDs, remaps pay items, creates contacts/projects/stock/employees in the demo Xero org, and enables Xero sync.

**Monitor:**
```bash
tail -f ~/logs/seed_xero_output.log
```

**Check:**
```bash
python scripts/restore_checks/check_xero_seed.py
```
Expected: Clients linked ~550, Stock synced ~440, Staff linked ~15

## Step 14: Final Sync

```bash
python manage.py start_xero_sync
```

**Check:** No errors in output.

## Step 15: Verify

- [ ] Log in as admin — Kanban board shows restored jobs
- [ ] Open a job — cost lines and events present
- [ ] Client page loads with contacts
- [ ] Staff list shows restored employees
- [ ] Admin > Xero shows "Connected"
- [ ] Create a test timesheet entry

## Cleanup

```bash
rm ~/prod_backup_*
```
