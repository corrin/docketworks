# Instance Setup: Production

Set up one client installation against that client's real Xero organisation.
Complete the client-onboarding prerequisites first: the required payroll
calendar, pay items, and invoice branding theme must **already exist** in the
client's Xero organisation before the instance is created. Production
onboarding validates those objects against the organisation; it never creates
them — creation of demo-only payroll objects is the `--seed-xero` path of the
[demo setup](instance-setup-demo.md), and it is refused against a production
organisation.

Server-level provisioning is [`server_setup.md`](server_setup.md).

## 1. Prepare persistent instance configuration

```bash
sudo scripts/server/instance.sh prepare-config <client> prod
sudoedit /opt/docketworks/config/<client>-prod.credentials.env
sudoedit /opt/docketworks/config/<client>-prod.company-defaults.json
```

Complete every required secret and replace every placeholder in the
company-defaults file, including the exact name of the existing Xero payroll
calendar. Set `xero_tenant_id` to any well-formed UUID — validation refuses a
missing or malformed value, and onboarding rebinds it to the connected tenant
(see
[README](../scripts/server/README.md#xero_tenant_id-in-the-company-defaults-json)).
Keep `enable_xero_sync` false; `instance.sh` refuses the file otherwise.

These root-owned files are the durable source for rebuilding and reconfiguring
the instance. `prepare-config` never overwrites either file.

## 2. Create the instance

```bash
sudo scripts/server/instance.sh create <client> prod --no-start
```

Creation refuses existing or partial state — repair by destroying the partial
state and creating again, never by `reconfigure` (see the last section). It
creates the infrastructure, runs migrations, and loads the configured Company
and CompanyDefaults. It does not create dummy staff or start application
services, and nothing scripted stores a bootstrap password; create the first
login interactively:

```bash
sudo scripts/server/dw-run.sh <client>-prod python manage.py createsuperuser
```

Check the app and Xero application configuration:

```bash
sudo scripts/server/dw-run.sh <client>-prod python -m scripts.ops.restore_checks.check_company_defaults
sudo scripts/server/dw-run.sh <client>-prod python -m scripts.ops.restore_checks.check_xero_app
sudo scripts/server/dw-run.sh <client>-prod python -m scripts.ops.restore_checks.check_integration_settings
```

### Point the workflow folder at the client's real files

`create` renders `DROPBOX_WORKFLOW_FOLDER` in the instance `.env` as an empty
instance-local directory. For a client whose job folders are Dropbox-synced
(Maestral on the host), edit the value to the synced directory that
**directly contains** the `Job-<number>` folders — the workflow subfolder,
never the Dropbox root — and keep the value quoted: `dw-run.sh` sources the
file, and an unquoted path containing a space aborts the source. One level too high 404s every attachment and creates
new job folders at the Dropbox top level while every daemon reports healthy
(2026-08-31 production incident). The edit survives `reconfigure`
(`render_instance_env` reads it back), and `verify-instance.sh` gates on
every `JobFile` row resolving to a file under the configured root.

## 3. Start services and authorise Xero

Sign in with the admin login, open Admin > Xero, and complete the OAuth flow.

In Admin > Settings, explicitly select the live Xero sales branding theme that
controls the client's required quote and invoice presentation. **Production
finalisation never selects a theme automatically** — only demo seeding may
take the first one — so the operator selects it here, before finalising.

Enter the approved quote wording in DocketWorks **Xero quote terms** (review
the initial wording generated from the company website's `/terms-of-trade`
page), then copy it exactly to Xero **Terms (Quotes)** so emergency quotes
created directly in Xero carry the same terms.

## 4. Finalise onboarding

```bash
sudo scripts/server/dw-run.sh <client>-prod python manage.py finalize_instance_onboarding
```

The command's contract
(`apps/xero/management/commands/finalize_instance_onboarding.py`), in order:

1. Disable automated sync, and require a completed Xero OAuth consent.
2. Run `xero --setup`: discover the connected tenant; validate the payroll
   calendar, pay items and selected branding theme against the organisation;
   store the tenant, shortcode, theme and calendar ids.
3. Sync pay items, then accounts.
4. Create the eleven canonical shop jobs.
5. Link the fixed leave types to their shop jobs.
6. Import staff through the normal Xero employee entity sync, deliberately
   last so payroll configuration exists first.
7. Set `enable_xero_sync=true` — the sequence's only re-open, reached only
   after every previous leg succeeds. There is no separate completion
   validation: each leg enforces its own contract.

Any failure exits non-zero, persists the error, and leaves automated Xero sync
disabled. Fix the source configuration and rerun the same command; it is
rerunnable.

## 5. Verify and hand over

- Staff list contains the expected Xero Payroll employees.
- Exactly eleven shop jobs are present.
- Admin > Xero reports connected.
- A normal Xero sync completes without errors.
- Test quote and invoice PDFs use the selected branding theme.
- A DocketWorks-created quote PDF contains the configured quote terms.
- DocketWorks **Xero quote terms** and Xero **Terms (Quotes)** contain the
  same approved wording.
- Give each imported staff member a Docketworks password. Imported employees
  have an unusable password until an administrator sets one; there is no
  self-service reset flow in this slice.
- Change the admin password if the one chosen at `createsuperuser` was shared
  during setup.

## Reconfigure is not repair

`instance.sh reconfigure <client> prod` exists for exactly one case: applying
edits to the persistent credentials of an **already complete** instance. It
refuses an incomplete instance, and `create` refuses partial state — a failed
creation is repaired by destroying the partial state and creating again, never
by reconfigure.

The CompanyDefaults JSON at
`/opt/docketworks/config/<client>-prod.company-defaults.json` is the rebuild
source. Live business settings are managed in the application afterwards; the
JSON seeds an instance, it does not track one.
