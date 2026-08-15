# Instance Setup: Demo

Create a non-production demonstration installation with 11 dummy staff and a
dedicated Xero Demo Company connection. Server-level provisioning (packages,
nginx, certificates) is [`server_setup.md`](server_setup.md); this runbook is
the demo-specific sequence on top of it. The production variant is
[`instance-setup-production.md`](instance-setup-production.md).

## 1. Prepare persistent instance configuration

```bash
sudo scripts/server/instance.sh prepare-config <client> uat --seed
sudoedit /opt/docketworks/config/<client>-uat.credentials.env
sudoedit /opt/docketworks/config/<client>-uat.company-defaults.json
```

Seeding is decided here: `--seed` selects the seeded company-defaults template,
and `create` below takes no `--seed` of its own. Complete the credentials and
keep `enable_xero_sync` false — `instance.sh` refuses a company-defaults file
with it true. Leave the seeded template's placeholder `xero_tenant_id` (the
zero UUID) alone: validation requires only a well-formed UUID, and the
`xero --setup` step below rebinds it to the connected organisation (see
[README](../scripts/server/README.md#xero_tenant_id-in-the-company-defaults-json)).
This is offline configuration; no DocketWorks services or OAuth flow are
involved.

## 2. Create the instance

```bash
sudo scripts/server/instance.sh create <client> uat --no-start
```

The command creates the infrastructure, runs migrations, and loads the
configured demo Company and CompanyDefaults without starting gunicorn or
Celery. Nothing scripted stores a bootstrap password, so create the first
login interactively:

```bash
sudo scripts/server/dw-run.sh <client>-uat python manage.py createsuperuser
```

Load the demo staff fixture (`apps/accounts/fixtures/initial_data.json` — 11
dummy staff plus the phone endpoint they answer; see the fixture's README)
with `manage.py loaddata` through `dw-run.sh`. Dummy staff initially have
**no** Xero employee ids, because those ids belong to a particular Xero
tenant; finalisation links them.

Verify the bootstrap data:

```bash
sudo scripts/server/dw-run.sh <client>-uat python -m scripts.ops.restore_checks.check_company_defaults
sudo scripts/server/dw-run.sh <client>-uat python -m scripts.ops.restore_checks.check_xero_app
```

## 3. Authorise the Xero Demo Company

Sign in with the admin login, open Admin > Xero, and complete the OAuth flow.

In Admin > Settings, enter demo wording in **Xero quote terms** that includes
the exact text `Terms of trade can be found` (the seeded template pre-fills a
suitable default). Copy the same wording to Xero's own **Terms (Quotes)**
setting: DocketWorks sends its copy on API-created quotes; Xero's copy covers
quotes created directly in Xero.

## 4. Finalise onboarding

```bash
sudo scripts/server/dw-run.sh <client>-uat python manage.py finalize_instance_onboarding --seed-xero
```

The explicit `--seed-xero`
flag may create missing demo-only payroll objects, including the configured
weekly calendar and required pay items — the same objects production
onboarding refuses to create. It then selects a live branding theme if none is
configured (demo seeding may take the first; production never does), syncs
accounts and pay items, links or creates Xero Payroll employees for the dummy
staff, creates the nine canonical shop jobs, validates the result, and enables
automated sync last. Failures exit non-zero and leave sync disabled; the
command is safe to rerun after correcting the cause.

The staff leg — linking or creating Xero Payroll employees — refuses loudly
until the payroll employee API is ported (a recorded Phase 4 deferral; see
[`v1-disposition.md`](v1-disposition.md)).

## 5. After a monthly Xero Demo Company reset

Xero recreates the Demo Company roughly monthly, and the replacement carries a
**new tenant id**. After each reset:

1. Re-run setup so it discovers the replacement tenant and rebinds
   CompanyDefaults and the tenant cache key:

   ```bash
   sudo scripts/server/dw-run.sh <client>-uat python manage.py xero --setup --seed-xero
   ```

2. Re-enter the Xero **Terms (Quotes)** wording in Xero — the reset wipes it,
   and without it quotes created directly in Xero carry no terms.

3. Re-provision payroll in the Xero web UI. A recreated organisation has the
   payroll product unprovisioned and no API turns it on; until it is activated
   every NZ Payroll call answers `403 Forbidden` with an empty body. See
   "Activate payroll in the Xero organisation" in
   [`restore-prod-to-nonprod.md`](restore-prod-to-nonprod.md#activate-payroll-in-the-xero-organisation).

## 6. Verify

- Staff list shows 11 demo employees, all linked to Xero Payroll. **Blocked
  today**: the payroll employee API is not yet ported, so the linking leg of
  finalisation refuses and the employees stay unlinked until it lands.
- Exactly nine shop jobs are visible.
- Admin > Xero reports connected.
- A normal Xero sync completes without errors.
- A test job, timesheet, quote, and invoice work as expected.
- The native Xero PDF for a DocketWorks-created quote contains
  `Terms of trade can be found`.

Logins:

- Admin: the credentials chosen at `createsuperuser`.
- Staff: their fixture email / `Default-staff-password`.
