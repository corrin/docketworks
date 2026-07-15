# Instance Setup: Demo

Onboard a prospect for a paid trial of DocketWorks. Uses dummy staff but the prospect's real rates, markups, and configuration. Connects to Xero Demo Company.

**Prerequisites:** Collect from the prospect before starting:
- Company name and acronym
- Charge-out rate, wage rate, time/materials markups, leave loading
- Working hours pattern
- Financial year start month, starting job/PO numbers, PO prefix

**Assumes:** Base server setup is complete (`scripts/server/server-setup.sh`).

---

## Step 1: Prepare Credentials

```bash
sudo scripts/server/instance.sh prepare-config <client> uat
```

Edit the root-owned credentials file:

```bash
sudoedit /opt/docketworks/config/<client>-uat.credentials.env
```

Fill in:
- XERO_DEFAULT_USER_ID — the existing Xero Demo Company login/user ID that will own time entries
- GCP_CREDENTIALS — shared dev service account key
- EMAIL credentials

XERO_DEFAULT_USER_ID must be present before `instance.sh create` runs.

Also fill in the Xero Client ID, Client Secret, Webhook Key, and Redirect URI
for the **Xero Demo Company** app. `instance.sh create` uses these values to
render and load the initial XeroApp fixture.

## Step 2: Create Instance

```bash
sudo scripts/server/instance.sh create <client> uat
```

**Check:** `https://<client>-uat.docketworks.site` shows login page.

## Step 3: Load Demo Data

```bash
# Company settings (starting point — will be customised in Step 5)
scripts/server/dw-run.sh <client>-uat python manage.py loaddata apps/workflow/fixtures/company_defaults.json

# Demo staff (11 dummy employees + admin)
scripts/server/dw-run.sh <client>-uat python manage.py loaddata apps/workflow/fixtures/initial_data.json
```

**Check:**
```bash
scripts/server/dw-run.sh <client>-uat python scripts/restore_checks/check_company_defaults.py
```

## Step 3.5: Check Xero App Credentials

```bash
scripts/server/dw-run.sh <client>-uat python scripts/restore_checks/check_xero_app.py
```

## Step 4: Configure Company Settings

In Admin > Settings, set the prospect's real values:
- Company name, acronym, address, email, website
- Charge-out rate, wage rate, markups, leave loading
- Working hours (Mon-Fri pattern)
- Financial year start month
- Starting job/PO numbers and PO prefix
- Shop client name

Upload logos: Admin > Settings > Company > Logo and Logo Wide.

## Step 5: Connect to Xero Demo Company

1. Log in as admin (`defaultadmin@example.com` / `Default-admin-password`)
2. Admin > Xero > "Login with Xero"
3. Authorize "Demo Company"

```bash
scripts/server/dw-run.sh <client>-uat python manage.py xero --setup
```

`xero --setup` stores the Demo Company's real default sales branding theme. In
Admin > Settings, change it to a terms-bearing theme if the default is not the
theme the prospect should see.

**Note:** `xero --setup` creates the "Weekly Testing" payroll calendar in the Demo Company if it's missing (a weekly calendar anchored to a **Monday** — Docketworks payroll posting requires Mon→Sun periods). If you ever create one by hand instead (Payroll > Settings > Payroll Calendars), its period **must start on a Monday**; `xero --setup` fails loudly if the calendar it just created came back on any other day.

## Step 6: Sync Xero Data

```bash
# Chart of accounts
scripts/server/dw-run.sh <client>-uat python manage.py start_xero_sync --entity accounts --force

# Pay items
scripts/server/dw-run.sh <client>-uat python manage.py xero --configure-payroll
```

## Step 7: Create Shop Jobs

```bash
scripts/server/dw-run.sh <client>-uat python manage.py create_shop_jobs
```

Creates: Annual Leave, Sick Leave, Bereavement Leave, Travel, Training, Business Development, Office Admin, Worker Admin, Bench.

Edit the leave jobs in Admin to set their Xero Pay Item.

## Step 8: Verify AI Providers

AI providers are configured during instance creation (`instance.sh create`). Verify:

```bash
scripts/server/dw-run.sh <client>-uat python scripts/restore_checks/check_ai_providers.py
```

## Step 9: Final Sync

```bash
scripts/server/dw-run.sh <client>-uat python manage.py start_xero_sync
```

## Step 10: Verify

- [ ] Log in as admin — dashboard loads
- [ ] Staff list shows 11 demo employees
- [ ] Shop jobs visible on Kanban board
- [ ] Admin > Xero shows "Connected"
- [ ] Can create a new job and add time/materials
- [ ] A DocketWorks quote and invoice use the selected Xero branding theme
- [ ] Create a test timesheet entry

## Login Credentials

- Admin: `defaultadmin@example.com` / `Default-admin-password`
- All staff: their email / `Default-staff-password`
