# Instance Setup: Demo

Create a non-production demonstration installation with 11 dummy staff and a
dedicated Xero Demo Company connection.

## 1. Prepare persistent instance configuration

```bash
sudo scripts/server/instance.sh prepare-config <client> uat --seed
sudoedit /opt/docketworks/config/<client>-uat.credentials.env
sudoedit /opt/docketworks/config/<client>-uat.company-defaults.json
```

Set `xero_tenant_id` in the company-defaults JSON to the UUID obtained outside
DocketWorks, complete the credentials, and keep `enable_xero_sync` false. This
is offline configuration; no DocketWorks services or OAuth flow are involved.

## 2. Create the instance

```bash
sudo scripts/server/instance.sh create <client> uat --seed --no-start
```

The command loads the configured demo Company/CompanyDefaults and 11 dummy
staff without starting gunicorn or Celery. Dummy staff initially have no Xero
employee IDs because those IDs belong to a particular Xero tenant.

Verify the bootstrap data:

```bash
scripts/server/dw-run.sh <client>-uat python scripts/restore_checks/check_company_defaults.py
scripts/server/dw-run.sh <client>-uat python scripts/restore_checks/check_xero_app.py
```

## 3. Authorise Xero Demo Company

Log in as `defaultadmin@example.com` / `Default-admin-password`, open Admin >
Xero, and complete the existing OAuth flow.

## 4. Finalise onboarding

```bash
scripts/server/dw-run.sh <client>-uat python manage.py finalize_instance_onboarding --seed-xero
```

The explicit flag may create missing demo-only payroll objects, including the
configured weekly calendar and required pay items. It then selects a live
branding theme if none is configured, syncs accounts and pay items, links or
creates Xero Payroll employees for all dummy staff, creates the nine canonical
shop jobs, validates the result, and enables automated sync last.

Failures exit non-zero and leave sync disabled. The command is safe to rerun
after correcting the cause.

After a monthly Xero Demo Company reset, run `xero --setup --seed-xero`; setup
discovers the replacement tenant and updates CompanyDefaults and the cache.

## 5. Verify

- Staff list shows 11 demo employees, all linked to Xero Payroll.
- Exactly nine shop jobs are visible.
- Admin > Xero reports connected.
- A normal Xero sync completes without errors.
- A test job, timesheet, quote, and invoice work as expected.

Logins:

- Admin: `defaultadmin@example.com` / `Default-admin-password`
- Staff: their fixture email / `Default-staff-password`
