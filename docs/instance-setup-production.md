# Instance Setup: Production

Set up one client installation against that client's real Xero organisation.
Complete the client-onboarding prerequisites first and ensure the required
payroll calendar, pay items, and invoice branding theme already exist in Xero.
Production onboarding validates those objects; it never creates them.

## 1. Prepare persistent instance configuration

```bash
sudo scripts/server/instance.sh prepare-config <client> prod
sudoedit /opt/docketworks/config/<client>-prod.credentials.env
sudoedit /opt/docketworks/config/<client>-prod.company-defaults.json
```

Complete every required secret and replace every placeholder in the
company-defaults file, including the exact name of the existing Xero payroll
calendar. Set `xero_tenant_id` to any valid placeholder UUID; onboarding rebinds
it (see
[README](../scripts/server/README.md#xero_tenant_id-in-the-company-defaults-json)).
Keep `enable_xero_sync` false.

These root-owned files are the durable source for rebuilding and reconfiguring
the instance. `prepare-config` refuses to overwrite either file.

## 2. Create the instance

```bash
sudo scripts/server/instance.sh create <client> prod --no-start
```

Creation refuses existing or partial state. It creates the infrastructure,
runs migrations, and loads the configured Company and CompanyDefaults before
creating the admin account. It does not create dummy staff or start application
services.

Check the app and private Xero app configuration:

```bash
scripts/server/dw-run.sh <client>-prod python scripts/restore_checks/check_company_defaults.py
scripts/server/dw-run.sh <client>-prod python scripts/restore_checks/check_xero_app.py
```

## 3. Start services and authorise Xero

Log in as `defaultadmin@example.com` / `Default-admin-password`, open Admin >
Xero, and complete the existing OAuth flow.

In Admin > Settings, explicitly select the live Xero sales branding theme that
contains the client's required quote and invoice terms. Production finalisation
does not select the first theme automatically.

## 4. Finalise onboarding

```bash
scripts/server/dw-run.sh <client>-prod python manage.py finalize_instance_onboarding
```

The command is rerunnable. It discovers and stores the connected tenant, then validates the payroll calendar,
pay items, and selected branding theme; stores the tenant, shortcode, theme and
calendar IDs; syncs pay items and accounts; imports active staff from Xero;
creates or updates the nine canonical shop jobs; runs completion checks; and
sets `enable_xero_sync=true` only after every step succeeds.

Any failure exits non-zero, persists the error, and leaves automated Xero sync
disabled. Fix the source configuration and rerun the same command.

## 5. Verify and hand over

- Staff list contains the expected Xero Payroll employees.
- Exactly nine shop jobs are present.
- Admin > Xero reports connected.
- A normal Xero sync completes without errors.
- Test quote and invoice PDFs use the selected terms-bearing theme.
- Password reset email works.
- Change the default admin password and have imported staff reset theirs.

Use `instance.sh reconfigure <client> prod` only after editing persistent
credentials for an already complete instance. The CompanyDefaults JSON is the
rebuild source; live business settings are subsequently managed in the app.
Reconfigure is not a repair command for partial creation.
