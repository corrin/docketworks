# Restore production to a non-production environment

Rebuild a development or UAT installation from production data and re-point its
Xero mirror at that installation's own demo organisation. Assume the repository
root as the working directory, `.env` loaded, and `uv` available; every command
below is written for that.

Two databases take part. The **source** database is v1-shaped: the scrubbed
production dump restores into it with its own schema, data and migration ledger.
The **target** database is this installation's own v2 database: it is dropped,
recreated, migrated, and then loaded from the source by
`scripts/ops/migrate_v1_data.sh`. Nothing loads a v1 dump directly into a v2
database — the two schemas differ, and the collision handling and re-normalisation
that make the load correct live in that script.

The dump itself is produced on the production host by `manage.py
backport_data_backup`, which pipes `pg_dump` into a temporary scrub database,
scrubs in place, and re-dumps the scrubbed copy. Raw production data never lands
on disk on either host, and the scrubbed dump carries no external-system
credentials.

## Audit

**Everything typed into this terminal is audited for legal compliance.** Every
command and its output is reviewed against this runbook, in order. Skipping
steps, running them out of order, or working around an error instead of stopping
are violations the audit catches.

## No workarounds

This process also runs unattended on server instances, where nobody is watching
to approve an improvisation. A workaround applied here fails silently there. If
anything goes wrong, stop and fix the underlying problem: do not skip the failing
step, do not run the steps after it, do not patch and continue.

The sections run in the order written. Reconnecting Xero is a hard gate — every
section after it assumes a connected organisation.

## Prerequisites

- `.env` configured with `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST` and the
  rest of the required variables. `DB_NAME` is how `config/settings.py` picks the
  target database, and it is what the production refusal in
  `apps/xero/operator_guards.py` inspects.
- An ssh route to the production host. `scripts/ops/pull_prod_backup.sh` runs
  `backport_data_backup` there as the instance user over `sudo`.
- The ngrok domain for this installation is up and registered as the Xero
  callback (see [`ngrok_setup.md`](ngrok_setup.md)). The OAuth consent later in
  this runbook only completes when the flow is started on that domain.
- `XERO_READONLY` unset for this session. The three Xero commands refuse to run
  under it, because the readonly provider returns fabricated ids and writing
  those into the mirror is the corruption these commands exist to repair.
- All application services stopped until the checks after the load pass.

## Pull the scrubbed dump

```bash
scripts/ops/pull_prod_backup.sh MSM dw_msm_prod
```

The first argument is the ssh target, the second the instance user that owns the
production venv and database role — also the database-name token in the dump
filename. Set `REMOTE_USER` when the ssh login differs from the local username:

```bash
REMOTE_USER=ubuntu scripts/ops/pull_prod_backup.sh MSM dw_msm_prod
```

The script generates the dump on the remote host, copies it into `restore/`,
removes the remote staging file, and runs `scripts/ops/verify_scrubbed_backup.py`
against the local copy.

**Check:** the run ends with `Verified scrubbed backup: restore/scrubbed_<...>.dump`.
The verifier fails when the archive is unreadable, predates the July 2026
migration squash, or still contains database-backed external-system credentials.
A failing archive is not restored — take a fresh one.

## Preserve the private configuration rows

The scrubbed dump strips `workflow_xeroapp` and `workflow_aiprovider`, so the
load leaves this installation with no Xero application registration and no AI
provider configuration. Both rows already exist in the target database and are
owned by this installation, not by production: copy them out before the load and
back in afterwards.

`workflow_xeroapp` is the single source of truth for Xero token material. Xero
rotates the refresh token on every refresh, so a copy taken anywhere else — an
old backup, an exported fixture, a note — is dead as soon as the next refresh
happens. The copy below is taken minutes before the load for that reason.

```bash
psql -d "$DB_NAME" -c "\copy workflow_xeroapp TO 'restore/xeroapp.csv' WITH (FORMAT csv)"
psql -d "$DB_NAME" -c "\copy workflow_aiprovider TO 'restore/aiprovider.csv' WITH (FORMAT csv)"
```

**Check:** both files exist and are non-empty. An empty `xeroapp.csv` means the
token material is already gone, and the re-consent later in this runbook is the
only way to get a working connection back.

The re-insert belongs immediately after the load, before anything reads Xero
configuration:

```bash
psql -d "$DB_NAME" -c "\copy workflow_xeroapp FROM 'restore/xeroapp.csv' WITH (FORMAT csv)"
psql -d "$DB_NAME" -c "\copy workflow_aiprovider FROM 'restore/aiprovider.csv' WITH (FORMAT csv)"
```

## Load the dump and migrate it into the target database

Restore the dump into a v1-shaped source database. It carries its own schema, so
this database needs nothing but to exist and be empty:

```bash
dropdb --if-exists dw_msm_v1
createdb dw_msm_v1
pg_restore --no-owner --no-privileges --exit-on-error -d dw_msm_v1 \
  restore/scrubbed_dw_msm_prod_<ts>.dump
```

Reset the target database and migrate it, in that order. `migrate` first and load
second is the rehearsed order: the seeds a fresh install writes (the system
automation staff row, the labour-subtype catalogue) are rows v1's dump also
carries, on UNIQUE columns, and the load is a single transaction where one
collision rolls back everything. `migrate_v1_data.sh` clears those seeds
immediately before restoring.

```bash
uv run python manage.py dbshell -- -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
uv run python manage.py migrate
scripts/ops/migrate_v1_data.sh dw_msm_v1 "$DB_NAME"
```

Then re-insert the private configuration rows from the previous section.

**Check:**

```bash
uv run python -m scripts.ops.validate_restored_data
uv run python -m scripts.ops.restore_checks.check_django_orm
uv run python manage.py showmigrations | grep '\[ \]'
```

`validate_restored_data.py` exits non-zero when the load holds a row v2 will
refuse to save: a dangling foreign key (`pg_restore --disable-triggers` skips
foreign-key enforcement, because those checks are triggers), a foreign key the
models declare required but the column left NULL, or a `full_clean()` violation.
`showmigrations` prints nothing when every migration is applied.
`scripts/ops/db_schema_diff.sh` and row-count parity belong to the cutover
rehearsal rather than to a refresh; see
[`cutover-checklist.md`](cutover-checklist.md).

## Development logins and the E2E user's flags

```bash
uv run python scripts/ops/setup_dev_logins.py
```

This creates the default admin and resets every staff password to a known
default, which is the point: the dump carries production password hashes.
Afterwards the admin is `defaultadmin@example.com` / `Default-admin-password`,
and every other staff member signs in with their own email and
`Default-staff-password`. Pass `--admin-only` to create the admin without
touching staff passwords — that is what instance provisioning uses.

Three properties of the E2E user are not carried by any production dump, because
production has no reason to hold them. Set them now, with the address in
`frontend/.env.test`'s `E2E_TEST_USERNAME`:

```bash
uv run python manage.py shell -c "
from apps.accounts.models import Staff
user = Staff.objects.get(email='<E2E_TEST_USERNAME>')
user.is_office_staff = True
user.is_superuser = True
user.base_wage_rate = 45.00
user.save()
print(user.email, user.is_office_staff, user.is_superuser, user.wage_rate)
"
```

`is_office_staff` gates the navbar's Create Job link, so the whole job cluster
stalls without it. Superuser gates the timesheet management surface, so the
timesheet cluster answers 403 without it. `wage_rate` is computed from
`base_wage_rate` on save, and the pricing pipeline refuses loudly on an
unconfigured wage, so a zero rate fails the cost-entry spec rather than costing
zero.

**Check:** the printed line shows the E2E user's email, both flags true, and a
non-zero wage rate.

## Company fixups

```bash
uv run python scripts/ops/fix_test_company.py
uv run python -m scripts.ops.restore_checks.fix_shop_company
```

`fix_test_company.py` creates the company named by
`CompanyDefaults.test_company_name` when it is missing; the Xero seed fails
without it. `fix_shop_company.py` repairs the shop company's name. Both are
idempotent.

**Check:** each prints either that it created the row or that the row already
existed.

## Job files

```bash
uv run python scripts/ops/recreate_jobfiles.py
```

The dump carries `JobFile` rows but no file bytes, so every attachment link is
broken until this fabricates a placeholder for each row.

**Check:** `uv run python -m scripts.ops.restore_checks.check_jobfiles` reports no
missing files.

## Post-restore checks

```bash
for s in scripts/ops/restore_checks/check_*.py; do uv run python "$s"; done
uv run python -m scripts.ops.restore_checks.test_serializers --verbose
uv run python -m scripts.ops.restore_checks.test_kanban_api
```

Each check prints its own success line and exits zero. A non-zero exit means the
step that should have produced that state did not — fix that step, rather than
re-running the check. `test_serializers.py` walks the restored dataset through
every wire contract a service function builds, and `test_kanban_api.py` proves
the kanban route answers over an authenticated request.

The Xero checks in this loop still describe the production organisation at this
point; they are re-run after the seed, where their answers become meaningful.

## Reconnect Xero

Start the development environment, then complete the OAuth consent in a browser
on this installation's ngrok domain:

```
https://<your-ngrok-domain>/api/xero/authenticate/
```

The flow must be started on that domain. Xero redirects to the callback
registered for the app, so a consent begun anywhere else cannot complete. v1
automated this with Playwright; that automation is not ported, and manual consent
is the current path (see [`v1-disposition.md`](v1-disposition.md)).

**Check:** the browser lands back on the application with a connected
organisation.

## Configure the Xero connection

```bash
uv run python manage.py xero --setup --seed-xero
uv run python manage.py xero --configure-payroll
```

`--setup` binds `CompanyDefaults` to the first connected organisation: it stores
the tenant id, sets the tenant cache key so the rest of the process resolves the
new id rather than the previous one, resolves the organisation shortcode, keeps a
still-present sales branding theme or falls back to the organisation's first, and
looks up the payroll calendar by name. `--seed-xero` additionally creates the
payroll configuration a fresh demo organisation lacks: a weekly calendar anchored
to a Monday, and any leave type or earnings rate present in the restored database
but missing from the organisation, matched by name. Payroll posting needs Monday
to Sunday periods, so setup aborts when Xero hands back a calendar anchored to any
other day. `--configure-payroll` then pulls leave types and earnings rates into
`XeroPayItem`.

**Check:** the configured tenant is one Xero currently reports as connected.

```bash
uv run python manage.py shell -c "
from xero_python.identity import IdentityApi
from apps.core.models import CompanyDefaults
from apps.xero.auth import get_api_client
live = {str(c.tenant_id): c.tenant_name for c in IdentityApi(get_api_client()).get_connections()}
configured = str(CompanyDefaults.get_solo().xero_tenant_id)
print('connected:', live)
print('configured:', configured, 'present:', configured in live)
"
```

A configured id absent from that list is the whole diagnosis of tenant drift: the
token is valid and every call still answers `403 AuthenticationUnsuccessful`,
because it is a token for an organisation that no longer exists. Re-running
`xero --setup` rebinds and refreshes the cache key. See "Environment facts worth
knowing" in [`rewrite-status.md`](rewrite-status.md) for the full playbook.

## Seed the demo organisation from the database

The restored database carries production Xero ids for entities the demo
organisation has never held. Seeding clears those ids and links or creates the
local records in the connected organisation, so the sync that follows matches
what is there instead of creating a second copy of everything.

Start with one small phase and confirm the batch-order tripwire stays quiet:

```bash
uv run python manage.py seed_xero_from_database --only contacts
```

Contact seeding maps Xero's batch response back to the submitted companies by
position, which assumes Xero preserves submission order; the tripwire aborts the
run when a returned name does not match the row it was mapped to. v1 verified the
assumption with a standalone probe that is not ported, so a small first batch is
what establishes it for this organisation.

Then run the rest. The full seed takes long enough to outlive a terminal:

```bash
mkdir -p logs
nohup uv run python manage.py seed_xero_from_database > logs/seed_xero_output.log 2>&1 &
echo "Seeding started, PID: $!"
tail -f logs/seed_xero_output.log
```

The phases are accounts, contacts, invoices, quotes and stock. The run clears the
production ids first, re-syncs pay items against the target organisation, and
finishes by setting `enable_xero_sync` to true — the sync is blocked until that
point.

**Check:** the log ends with the seeding-complete line and the warning that
payroll employees were not seeded. Re-running with `--skip-clear` reports nothing
created; that is the idempotence proof.

### What the seed commands refuse, and why

- **The production refusals run before every phase**, including under
  `--dry-run` and `--skip-clear`. Two independent checks: a `DB_NAME` ending in
  `_prod`, and a connected tenant equal to `PRODUCTION_XERO_TENANT_ID`. Either
  one raises, so the command exits non-zero and nothing runs. A wrapper that
  ignores exit codes sees a quiet run and concludes the seed succeeded.
- **An unmappable batch response raises mid-seed.** Part of the batch is linked
  and the rest is not, and re-running as-is repeats the failure because Xero
  renumbers a document number it already holds. The message names the remedy:
  delete the renumbered document, fix the local number, re-run with
  `--skip-clear --only invoices` or `--only quotes`. The `--skip-clear` re-run
  heals every stranded record, because linking is by name for contacts and by
  document number for invoices and quotes.
- **`--skip-clear` also skips the pay-item re-sync**, which is gated on the clear
  phase having run. The next `start_xero_sync` re-syncs pay items itself, and its
  referential check fails loudly rather than silently if any referenced item is
  still unmatched. The window between the two is documented behaviour, not a
  defect.
- **`--only` is not a pure phase filter.** Any run that clears also re-syncs pay
  items, because clearing nulls every pay-item id while jobs and cost lines still
  reference them, and leaving those references dangling is worse than doing extra
  work.
- **Pull-only mirrors keep their restored production ids.** `Bill`, `CreditNote`
  and `XeroPaySlip` are populated by the sync and never pushed, so the clear phase
  does not touch them and a refreshed installation legitimately holds rows still
  carrying production ids. Pay runs self-heal on the next sync, which deletes
  local rows the organisation does not have.

## Sync

```bash
uv run python manage.py start_xero_sync
```

The generator runs in this process, so a failing sync fails the command instead
of disappearing into a worker log. The command holds the shared sync lock for the
whole run, which is what stops it interleaving with a beat-dispatched Celery sync;
it publishes a run id but no messages, so the sync-status interface shows a run in
progress with an empty message list for the duration of an inline run.

**Check:** the run completes without errors, and the Xero checks in
`scripts/ops/restore_checks/` now pass against the target organisation:

```bash
uv run python -m scripts.ops.restore_checks.check_xero_accounts
uv run python -m scripts.ops.restore_checks.check_xero_seed
```

## Full E2E

```bash
./scripts/ops/run_e2e.sh
```

The script refuses an already-running environment, resets recognised E2E data,
owns the full service stack, restores the database afterwards and stops only what
it started. Run it in the foreground and let teardown finish: teardown is what
restores the database and writes the Xero token material back.

**Check:** the suite and its teardown both pass.

## What only a live run proves

These hold no unit test, and a restore that has not exercised them has not
established them:

- Xero preserves the submission order of a create-contacts batch.
- A payroll calendar created by `--seed-xero` really is anchored to a Monday
  after Xero has stored it.
- The demo organisation has an expense account available to borrow for a created
  earnings rate.
- Real quota behaviour under a full seed, including the daily floor.
- The sync that follows the seed creates no duplicates.
- `seed_xero_from_database --skip-clear` re-run reports nothing created.

## File locations

- Scrubbed dump, consumer side: `restore/scrubbed_<instance-user>_<ts>.dump`
- Scrubbed dump, producer side on the production host: `<BASE_DIR>/restore/`
- Preserved private configuration: `restore/xeroapp.csv`, `restore/aiprovider.csv`
- Seed log: `logs/seed_xero_output.log`

Keep the source dump until the E2E suite has passed. `restore/` also holds the
E2E harness's own recovery artefacts, so never remove it recursively — remove the
named dump once the operator approves.
