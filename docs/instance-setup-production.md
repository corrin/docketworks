# Instance Setup: Production

Set up a production instance for a client connecting to their real Xero organisation.

**Prerequisites:** Complete Phase 1-5 of [client_onboarding.md](client_onboarding.md) first (collect company details, configure Xero, create GCP service account, set up AI providers, configure email).

**Assumes:** Base server setup is complete (`scripts/server/server-setup.sh`).

---

## Step 1: Prepare Credentials

```bash
sudo scripts/server/instance.sh prepare-config <client> prod
```

Edit the root-owned credentials file:

```bash
sudoedit /opt/docketworks/config/<client>-prod.credentials.env
```

Fill in:
- XERO_DEFAULT_USER_ID — the existing Xero login/user ID that will own time entries
- GCP_CREDENTIALS path (from Phase 3a of client_onboarding.md)
- EMAIL_HOST_USER + EMAIL_HOST_PASSWORD

XERO_DEFAULT_USER_ID must be present before `instance.sh create` runs.

Also fill in the Xero Client ID, Client Secret, Webhook Key, and Redirect URI
from the client's Xero app. `instance.sh create` uses these values to render
and load the initial XeroApp fixture.

## Step 2: Create Instance

```bash
sudo scripts/server/instance.sh create <client> prod
```

Creates: OS user, database, .env, code clone, frontend build, migrations, admin user, systemd services (gunicorn + celery), nightly backup timer, and nginx config.

**Check:** `https://<client>-prod.docketworks.site` shows login page.

## Step 2.5: Check Xero App Credentials

```bash
scripts/server/dw-run.sh <client>-prod python scripts/restore_checks/check_xero_app.py
```
Expected: `XeroApp configured: <client>-prod xero`.

## Step 3: Connect to Xero

Log into the app as admin (`defaultadmin@example.com` / `Default-admin-password`).

Admin > Xero > "Login with Xero" > Authorize the client's Xero organisation.

**Check:** in **Admin > Xero Apps** the row shows `Authorised: ✓`.
(There's no CLI check for this — `check_xero_app.py` is a pre-OAuth
existence check and doesn't read tokens.)

## Step 4: Configure Xero

```bash
scripts/server/dw-run.sh <client>-prod python manage.py xero --setup
```

Sets xero_tenant_id, xero_shortcode, and xero_payroll_calendar_id.

**Requires:** The payroll calendar must already exist in Xero (created during client onboarding Phase 2a).

## Step 5: Configure Company Settings

In Admin > Settings, set all values collected in Phase 1 of client_onboarding.md:
- Company name, acronym, address, email, website, phone
- Charge-out rate, wage rate, markups, leave loading
- Working hours (Mon-Fri pattern)
- Financial year start month
- Starting job/PO numbers and PO prefix
- Shop client name (must match the Xero contact from Phase 2a)
- Google Drive folder IDs (Shared Drive, How We Work, SOPs, Reference Library)
- Quote template ID and quotes folder ID (if applicable)

Upload logos: Admin > Settings > Company > Logo and Logo Wide.

## Step 6: Sync Xero Data

```bash
# Chart of accounts
scripts/server/dw-run.sh <client>-prod python manage.py start_xero_sync --entity accounts --force

# Pay items
scripts/server/dw-run.sh <client>-prod python manage.py xero --configure-payroll
```

**Check:**
```bash
scripts/server/dw-run.sh <client>-prod python scripts/restore_checks/check_xero_accounts.py
```
Expected: `Total accounts synced: ~60+`

## Step 7: Import Staff from Xero

```bash
# Preview first
scripts/server/dw-run.sh <client>-prod python manage.py xero --import-staff-dry-run

# Import
scripts/server/dw-run.sh <client>-prod python manage.py xero --import-staff
```

This creates Staff records from Xero Payroll employees with wage rates and working hours. All imported staff get `password_needs_reset=True`.

## Step 8: Create Shop Jobs

```bash
scripts/server/dw-run.sh <client>-prod python manage.py create_shop_jobs
```

Creates: Annual Leave, Sick Leave, Bereavement Leave, Travel, Training, Business Development, Office Admin, Worker Admin, Bench.

Edit the leave jobs in Admin to set their Xero Pay Item (Annual Leave → Annual Leave type, etc.).

## Step 9: Configure AI Providers

In Admin > AI Providers, add each provider:
- Provider type, model name, API key
- Mark one as default

## Step 10: Import Documents (if applicable)

If SOPs were uploaded to Google Drive (Phase 3d of client_onboarding.md):

```bash
scripts/server/dw-run.sh <client>-prod python manage.py import_dropbox_hs_documents
```

## Step 11: Start Xero Sync

```bash
scripts/server/dw-run.sh <client>-prod python manage.py start_xero_sync
```

**Check:** No errors in output. Xero data appears in the app.

## Step 12: Verify

- [ ] Log in as admin — dashboard loads
- [ ] Staff list shows imported employees
- [ ] Shop jobs visible on Kanban board
- [ ] Create a test timesheet entry
- [ ] Admin > Xero shows "Connected" status
- [ ] Password reset email works (test with a staff member)

## Post-Setup

- Change admin password from the default
- Have each staff member log in and set their password
- Monitor Xero sync for the first few days
