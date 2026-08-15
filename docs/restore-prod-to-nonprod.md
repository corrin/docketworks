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
credentials. The producer needs the instance's `dw_<client>_<env>_scrub`
database and the `SCRUB_DB_NAME` line in its `.env`: instances are created with
both, and an instance created before they existed gains them with one
`sudo scripts/server/instance.sh reconfigure <client> <env>` on its host. The
producer also writes a `<dump>.migrations.json` snapshot of the production
migration ledger beside the archive, for `scripts/ops/migrate_to_snapshot.py`.

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

The sections run in the order written. A connected Xero organisation is a hard
gate — every section after "Reconnect Xero" assumes one, whether the token
preserved across the load supplied it or a fresh consent did.

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
- `XERO_READONLY=false` for this session — set explicitly, never unset: the
  variable is in `config/settings.py`'s `REQUIRED_ENV_VARS`, so with it unset
  every `manage.py` command in this runbook dies at startup before doing
  anything. The three Xero commands refuse to run when it is true, because the
  readonly provider returns fabricated ids and writing those into the mirror is
  the corruption these commands exist to repair. The flag is per-process: the
  Django server, the Celery worker and Celery beat sharing this database must
  all carry the same value, or a reconnected Xero can write to the real
  organisation through whichever process was started without it.
- All application services stopped until the checks after the load pass.

## Connection settings for the raw database steps

`manage.py` and the ported scripts read the `DB_*` keys from `.env`. The raw
`psql`, `pg_restore`, `createdb` and `dropdb` commands in this runbook do not:
libpq reads `PGUSER`, `PGHOST` and `PGPASSWORD`, and falls back to the
operator's own OS user, which a database owned by the `postgres` role refuses.
Export the `.env` values once, at the start of the session, and every raw
command below connects the way Django does:

```bash
export PGUSER="$(grep -E '^DB_USER=' .env | cut -d= -f2-)"
export PGPASSWORD="$(grep -E '^DB_PASSWORD=' .env | cut -d= -f2-)"
export PGHOST="$(grep -E '^DB_HOST=' .env | cut -d= -f2-)"
export PGPORT="$(grep -E '^DB_PORT=' .env | cut -d= -f2-)"
export DB_NAME="$(grep -E '^DB_NAME=' .env | cut -d= -f2-)"
```

**Check:**

```bash
psql -d "$DB_NAME" -c "SELECT current_user, current_database()"
```

It prints the user and database named in `.env`. A "role does not exist" or a
peer-authentication failure here means the exports did not take, and every raw
step below would fail the same way — fix it now rather than at the first one.

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
runs `scripts/ops/verify_scrubbed_backup.py` against the local copy and prints
its SHA-256. Removing the remote staging file happens in the script's exit trap,
after those lines; a failed run removes the local copy instead of keeping a
half-trusted archive.

**Check:** three consecutive lines name the local dump by absolute path and
carry its checksum, followed by the exit trap's remote-cleanup line:

```
Verified scrubbed backup: /…/restore/scrubbed_dw_msm_prod_<ts>.dump
>> SHA-256: <hash>
>> Done: /…/restore/scrubbed_dw_msm_prod_<ts>.dump
>> Removing remote staging file...
```

The verifier fails when the archive is unreadable, predates the July 2026
migration squash, or still contains database-backed external-system credentials.
A failing archive is not restored — take a fresh one.

## Preserve the private configuration rows

The scrubbed dump strips `workflow_xeroapp` and `workflow_aiprovider`, so the
load leaves this installation with no Xero application registration and no AI
provider configuration. Both rows already exist in the target database and are
owned by this installation, not by production: copy them out before the load and
back in afterwards.

A fresh target database is the one branch here: it has no rows to preserve, so
skip the copy-out, and after the load bootstrap both rows from the dev fixtures
instead (see "Private configuration" in
[`initial_install.md`](initial_install.md)).

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

On a server instance the re-insert is not a CSV round trip: regenerate and load
the instance-owned private fixtures from the root-owned credentials file
instead —

```bash
sudo scripts/server/instance.sh reconfigure "<client>" "<env>"
```

Immediately after the re-insert, force the sync gate off:

```bash
uv run python manage.py shell -c "
from apps.core.models import CompanyDefaults
CompanyDefaults.set_xero_sync_enabled(enabled=False)
assert not CompanyDefaults.get_solo().enable_xero_sync
"
```

The restored value is true — production runs with the sync on and the scrubber
does not touch `enable_xero_sync` — so without this step the gate is open the
moment the load commits. Trusting the seed's own refusals instead was rejected:
they guard the seed command, not the beat-dispatched Celery sync, and a sync
dispatched between the Xero reconnect and the seed pushes production-id rows at
the demo organisation — the exact duplication the seed exists to prevent. The
seed re-enables the gate as its final act.

Local dev deliberately has no `PhoneProviderSettings` row, so dev Celery cannot
reach the production phone system. On a local dev restore, assert that absence
rather than assuming it:

```bash
uv run python manage.py shell -c "
from apps.crm.models import PhoneProviderSettings
assert not PhoneProviderSettings.objects.exists(), 'phone provider must be unconfigured on local dev'
"
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
uv run python manage.py reset_public_schema --database "$DB_NAME"
uv run python manage.py migrate
scripts/ops/migrate_v1_data.sh dw_msm_v1 "$DB_NAME" -U "$PGUSER" -h "$PGHOST" -p "$PGPORT"
```

`reset_public_schema` is the sanctioned wipe (ADR 0048): `--database` must
name the configured `DB_NAME` (script-safe as `"$DB_NAME"`), and it takes a
pre-wipe snapshot to `backups/pre_reset_<db>_<ts>.sql.gz` by default —
aborting the wipe if the dump fails — so this step is always recoverable.
Add `--skip-backup` only when a fresh snapshot already exists (the
troubleshooting section below does). A `_prod`-suffixed database
additionally demands `--wipe-production`, which this runbook deliberately
does not carry: copy-pasting these lines against production fails. A raw
`dbshell -- -c "DROP SCHEMA public CASCADE"` was rejected as the process
here: it carries no refusals and no recovery path, and this runbook also
runs unattended.

Everything after the two database names is passed through to the script's
`psql`, `pg_dump` and `pg_restore` calls. Naming the connection there rather
than relying on the exported variables keeps those calls and the script's own
`manage.py migrate` step — which reads `.env` — pointed at the same server even
when the script runs from a shell that did not export them.

Then re-insert the private configuration rows and force the sync gate off, as
written in the previous section.

**Check:**

```bash
uv run python -m scripts.ops.restore_checks.check_django_orm
uv run python manage.py showmigrations | grep '\[ \]'
```

These two answer "did the load complete", which is a different question from
"is the data v2-valid" — the ORM answers and the core tables hold plausible
counts, and `showmigrations` prints nothing when every migration is applied.
Validation comes after the development logins below, for the reason given
there. `scripts/ops/db_schema_diff.sh` and row-count parity belong to the
cutover rehearsal rather than to a refresh; see
[`cutover-checklist.md`](cutover-checklist.md).

## Demo company defaults, on dev and demo restores only

The load carries the production company name into `CompanyDefaults`, and the
production logo path with it — but the logo bytes never arrive on a dev
restore, so the row points at an image that does not exist. Replace both with
the shipped demo values:

```bash
uv run python manage.py loaddata apps/core/fixtures/company_defaults.json
uv run python manage.py shell -c "
from apps.core.models import CompanyDefaults
CompanyDefaults.set_xero_sync_enabled(enabled=False)
assert not CompanyDefaults.get_solo().enable_xero_sync
"
```

The gate-off is repeated after the loaddata because the fixture rewrites the
whole `CompanyDefaults` row, and this step must hold the gate closed however
the fixture evolves. The fixture also sets
`xero_payroll_calendar_name="Weekly Testing"` and
`test_company_name="ABC Carpet Cleaning TEST IGNORE"` — the values
`xero --setup` and `fix_test_company.py` later match on.

This step is for dev and demo restores only. The durable source for a
tenant-specific server rebuild remains the root-owned
`/opt/docketworks/config/<name>.company-defaults.json`; do not maintain a
second long-lived instance copy of that file.

## Development logins

```bash
uv run python scripts/ops/setup_dev_logins.py
```

This creates the default admin and resets every staff password to a known
default, which is the point: the dump carries production password hashes.
Afterwards the admin is `defaultadmin@example.com` / `Default-admin-password`,
and every other staff member signs in with their own email and
`Default-staff-password`. Pass `--admin-only` to create the admin without
touching staff passwords — that is what instance provisioning uses.

**This step runs before validation, not after, because it is part of what makes
the load valid.** The production scrubber deliberately leaves password fields
alone, and production legitimately holds staff who have never signed in and
therefore carry a blank password. v2's `Staff` contract requires a hash, so
those rows fail `validate_restored_data.py`'s model sweep — a real refusal
against real data, not a false positive. Resetting every password is what
makes them valid. Running validation first and documenting the failure as
expected was rejected: an expected-failure allowance teaches an operator to read
past red, and ADR 0015 says fix the data rather than tolerate it, which this
reset does.

**Check:** the run prints `Created admin user:` or `Admin user already exists:`,
then `Reset passwords for <n> staff members.` and the two credential lines. A
zero count there means no staff arrived in the load, which is a defect in the
load, not in this step.

## Validate the restored data

```bash
uv run python -m scripts.ops.validate_restored_data
```

It exits non-zero when the load holds a row v2 will refuse to save: a dangling
foreign key, a foreign key the models declare required but the column left NULL,
or a `full_clean()` violation. The load defers foreign-key checks to the commit
of its single transaction, and foreign keys Django declares
`db_constraint=False` are never enforced by the database at all, so the sweep
re-proves every reference in bulk afterwards.

**Check:** the run ends `TOTALS: dangling foreign keys 0, required references
NULL 0, rows failing validation 0` and exits zero. Any other totals print
`Fix the DATA, not the reader (ADR 0015).` and exit 1 — the sweep names the
model, the count and an example primary key for each failure.

## The E2E user

Playwright signs in as the user named in `frontend/.env.test`, and **no
production dump carries that user** — the address exists only in
non-production. This step creates it on a first refresh and re-aligns its
password afterwards, when `setup_dev_logins.py` has just reset every password to
the staff default and left Playwright's stored one wrong. Either way
`global-setup.ts` fails at sign-in without it, and a failure there means the
suite never starts.

```bash
uv run python manage.py shell -c "
import pathlib
from apps.accounts.models import Staff
env = dict(
    line.split('=', 1)
    for line in pathlib.Path('frontend/.env.test').read_text().splitlines()
    if '=' in line and not line.lstrip().startswith('#')
)
email = env['E2E_TEST_USERNAME']
user = Staff.objects.filter(email=email).first()
if user is None:
    user = Staff.objects.create_user(
        email=email, password=env['E2E_TEST_PASSWORD'], first_name='E2E', last_name='Test'
    )
else:
    user.set_password(env['E2E_TEST_PASSWORD'])
    user.save()
print(user.email, 'password matches .env.test:', user.check_password(env['E2E_TEST_PASSWORD']))
"
```

The other direction — writing `E2E_TEST_PASSWORD=Default-staff-password` into
`frontend/.env.test` — would re-align an existing user and is rejected: that
file is tracked, so the edit shows up in `git status` on every refresh and is
one careless `git commit -a` away from publishing a credential. It also does
nothing about the user being absent. Reading the value out of the file keeps the
password off the command line and out of shell history.

**Check:** the printed line ends `password matches .env.test: True`.

Three properties of that user are not carried by any production dump either,
because production has no reason to hold them. Set them now, with the same
address:

```bash
uv run python manage.py shell -c "
from decimal import Decimal
from apps.accounts.models import Staff
user = Staff.objects.get(email='<E2E_TEST_USERNAME>')
user.is_office_staff = True
user.is_superuser = True
user.base_wage_rate = Decimal('37.50')
user.save()
print(user.email, user.is_office_staff, user.is_superuser, user.wage_rate)
"
```

`is_office_staff` gates the navbar's Create Job link, so the whole job cluster
stalls without it. Superuser gates the timesheet management surface, so the
timesheet cluster answers 403 without it. `wage_rate` is computed on save as
`base_wage_rate` times one plus the annual leave loading — 20% in the demo
company defaults, so 37.50 computes to exactly **45.00**, which is the value
`job-cost-entry-data.spec.ts` pins as its environment prerequisite
(`E2E_USER_WAGE_RATE`). Setting `base_wage_rate = 45.00` was the rejected
obvious move: it computes a 54.00 wage and fails that spec's labour-cost
assertion while passing every "non-zero" check on the way.

**Check:** the printed line shows the E2E user's email, both flags true, and a
wage rate of exactly `45.00`.

## Company fixups

```bash
uv run python scripts/ops/fix_test_company.py
uv run python -m scripts.ops.restore_checks.fix_shop_company
```

`fix_test_company.py` creates the company named by
`CompanyDefaults.test_company_name` when it is missing; the Xero seed fails
without it. `fix_shop_company.py` restores the shop company's name, which the
production scrub anonymises.

**Check:** `fix_test_company.py` prints either `Test company already exists:
<name> (ID: …)` or `Created test company: <name> (ID: …)`. It raises
`RuntimeError` and exits non-zero when `CompanyDefaults.test_company_name` is
unset: set that field and re-run rather than creating the company by hand, since
the seed matches on the same field.

`fix_shop_company.py` rewrites the name unconditionally, so a successful run
always prints `Updated shop company:` followed by the old and new names, the
fixed shop id and the job count, and exits zero — there is no "already correct"
output to wait for. `ERROR: Shop company with ID
00000000-0000-0000-0000-000000000001 not found` with exit 1 means the load did
not carry the shop company, which is a defect in the load rather than something
this script can repair.

## Job files

```bash
uv run python scripts/ops/recreate_jobfiles.py
```

The dump carries `JobFile` rows but no file bytes, so every attachment link is
broken until this fabricates a placeholder for each row.

**Check:** `uv run python -m scripts.ops.restore_checks.check_jobfiles` prints
`Missing files: 0` and exits zero. Any other count exits 1 and names how many
rows still have no file on disk.

## Post-restore checks

```bash
(for s in scripts/ops/restore_checks/check_*.py; do uv run python "$s" || exit 1; done)
echo "checks exited $?"
uv run python -m scripts.ops.restore_checks.test_serializers --verbose
uv run python -m scripts.ops.restore_checks.test_kanban_api
```

The loop runs in a subshell so the first failing check stops it with a non-zero
status a wrapper can read; a bare `|| exit 1` would do the same in a script and
close the terminal of an operator running this by hand.

A non-zero exit means the step that should have produced that state did not —
fix that step, rather than re-running the check. `test_serializers.py` walks the
restored dataset through every wire contract a service function builds, and
`test_kanban_api.py` proves the kanban route answers over an authenticated
request.

Every check in the loop exits non-zero on failure except `check_xero_seed.py`.
Two of them gate on state an earlier step of this runbook was supposed to
produce: `check_jobfiles.py` fails when any `JobFile` row has no file behind it,
and `check_xero_accounts.py` fails when the chart of accounts holds no account
named `Sales`, or one whose code is blank — that account is what every seeded
invoice and quote line is coded to. It also prints whether codes 200 and 300 are
present, as information only: those are Xero's default chart codes, a real
production chart need not use them, and stock sync falls back to the first
expense account by code when 300 is absent.
`check_xero_seed.py` is the single exception and is informational by design: it
prints how many records carry a Xero id and exits zero whatever the counts are,
because the right number depends entirely on the restored dataset. Read it; do
not wait for it to fail.

The Xero checks in this loop still describe the production organisation at this
point; they are re-run after the seed, where their answers become meaningful.

## Reconnect Xero, only if the preserved token no longer authenticates

Ask Xero what this installation is connected to before assuming anything:

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

**If that command answers at all, skip the consent and go on to the next
section** — an answer means the preserved `workflow_xeroapp` row still holds
working token material, which is the normal outcome, because preserving that row
across the load is a step of this runbook. Whether `present:` says True or False
does not change that: a configured id missing from the list is tenant drift, and
`xero --setup` repairs it below by rebinding to the connected organisation.
Consenting again anyway would throw away the row the earlier step went out of its
way to keep.

Consent is for one case only: the call fails to authenticate, raising
`NoValidXeroTokenError` or failing its token refresh with a 401. Then the stored
refresh token is genuinely dead and a browser round trip is the only way to get a
new one.

Do it in this order, because both halves depend on the ngrok domain:

1. Start the development environment and sign in to the application **on the
   ngrok domain**. `xero_authenticate` enforces the office-staff cookie JWT
   itself, and the load wiped every session, so a browser tab left open from
   before the refresh carries a dead cookie and the endpoint refuses.
2. In that same signed-in browser, open:

   ```
   https://<your-ngrok-domain>/api/xero/authenticate/
   ```

The flow must both start and finish on that domain: Xero redirects to the
callback registered for the app, so a consent begun anywhere else cannot
complete. v1 automated this with Playwright; that automation is not ported, and
manual consent is the current path (see
[`v1-disposition.md`](v1-disposition.md)).

**Check:** the browser lands back on the application, and re-running the
connections command above now prints the organisation.

## Activate payroll in the Xero organisation

A recreated demo organisation has the payroll product unprovisioned, and there is
no API that turns it on. Open Payroll in the Xero web UI for this organisation
once, as a browser step, and complete whatever activation prompt it shows.

Until that is done every NZ Payroll call — including the ones
`xero --setup --seed-xero` and `xero --configure-payroll` make below — answers
**`403 Forbidden` with an empty body**, while everything about the connection
looks correct: the token is valid, `get_connections` lists the organisation, the
tenant id in the request headers is the right one, and the stored scope string
carries every payroll scope.

The two 403s a refresh produces are different failures and the body is what
tells them apart:

- **Empty body** — payroll is not provisioned for this organisation. Activate it
  in the browser as above.
- **Body naming the error**, `{"Title":"Forbidden","Detail":"AuthenticationUnsuccessful"}`
  — tenant drift: a valid token for an organisation that no longer exists. Re-run
  `xero --setup`, and see "Environment facts worth knowing" in
  [`rewrite-status.md`](rewrite-status.md).

**Check:** `uv run python manage.py xero --configure-payroll` in the next section
reaches Xero instead of answering 403.

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

**Check:** re-run the connections command from "Reconnect Xero". It now has to
print `present: True` — the same command, read as a verification rather than as
a decision. Written out once rather than twice on purpose: two copies drift, and
the second one silently stops matching what the first proves.

`present: False` here means `--setup` bound to a different organisation from the
one `CompanyDefaults` names, which is the tenant-drift signature — a valid token
for an organisation that no longer exists, whose every call answers `403` with an
`AuthenticationUnsuccessful` body. `--setup` rebinds to the first connected
organisation and refreshes the cache key, so a second run against a single
connection resolves it; see "Environment facts worth knowing" in
[`rewrite-status.md`](rewrite-status.md) for the full playbook.

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

The run clears the production ids first, then walks the phases in order:
accounts, contacts, invoices, quotes, stock. The pay-item re-sync sits between
the contacts and invoices phases, because the clear nulled the pay-item ids that
jobs and cost lines reference. **Only a FULL successful run re-opens the
sync gate** (`enable_xero_sync=True`, the gate this runbook forced off after
the load); a partial `--only` run leaves the gate exactly as it found it.
The seed is a batch process — syncing may exist only after the whole batch
reports success, because an open gate mid-batch lets beat syncs and webhook
echoes interleave with the batch's own writes. The gate is not closed by the
restore itself: the dump arrives with it true, and only the explicit
gate-off step holds the sync back until the seed has run.

**Check:** the log ends with the seeding-complete line and the warning that
payroll employees were not seeded. Re-running with `--skip-clear` reports nothing
created; that is the idempotence proof.

Then verify document presentation by hand — a successful API seed alone does
not verify document content or presentation. Open one recreated quote and one
recreated invoice in Xero and confirm their native PDFs use the selected
destination branding theme and carry the quote terms configured in
`CompanyDefaults`. Copy that same wording into the destination organisation's
**Terms (Quotes)** field, so quotes raised directly in Xero fall back to the
same terms.

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

## Snapshot the verified database

The database is now in a known-good state: loaded from production, migrated,
fixups applied, Xero seeded and synced, every check green. Capture that state
so the Playwright run — or any later test run — can be recovered from it
without re-running this entire runbook.

```bash
mkdir -p backups
TS=$(date +%Y%m%d_%H%M%S)
OUT="backups/post_restore_${TS}.sql.gz"

# Atomic write: dump to .tmp, rename on success. pipefail because gzip
# succeeds on empty stdin, which would otherwise hide a pg_dump failure.
set -o pipefail
pg_dump -d "$DB_NAME" | gzip > "$OUT.tmp"
mv "$OUT.tmp" "$OUT"
set +o pipefail

echo "Baseline snapshot: $OUT"
```

`pg_dump` connects through the `PG*` variables exported at the start of the
session, the same way every raw command in this runbook does.

**Check:**

```bash
ls -lh backups/post_restore_*.sql.gz | tail -1
```

The newest file carries this run's timestamp and is at least a few megabytes —
a gzipped full dump, not the empty output of a failed pipe.

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

## Troubleshooting

### Sync fails: a name is already linked to a different Xero ID

`start_xero_sync` aborts with `Name '<x>' already linked to Xero ID <a>,
cannot link to <b>` when the organisation holds two ACTIVE contacts with
one name — sync machinery ran while a bulk operation was mid-batch (the
sequencing the sync gate exists to prevent), and the sync's same-name guard
stops rather than guessing which contact is real.

Merge the duplicates in the Xero UI — merging is Xero's own dedupe and its
only one: there is no merge API, and API writes against such a pair are
silently discarded (200 with the payload echoed back, nothing persisted).
Check which ID the local row references first
(`Company.objects.get(name='<x>').xero_contact_id`; the contact ID is in
the Xero contact page's URL) and merge the OTHER contact into it. After
the merge, the losing contact can read ACTIVE for some time before
settling to `ARCHIVED` with `merged_to_contact_id` set; once it settles,
re-run `start_xero_sync` — the sync's merged-contact branch records the
husk as an archived company and proceeds.

### E2E teardown failed to restore the database

`global-teardown.ts` printed its failed-to-restore banner, or the database
holds rows Playwright created. Restore the newest baseline snapshot:

```bash
LATEST=$(ls -t backups/post_restore_*.sql.gz | head -1)
echo "Restoring from: $LATEST"

uv run python manage.py reset_public_schema --database "$DB_NAME" --skip-backup
gunzip -c "$LATEST" | psql -v ON_ERROR_STOP=1 --single-transaction -d "$DB_NAME"
```

`--skip-backup` is right here and only here: `$LATEST` is already the
recovery point, and dumping the Playwright-dirtied database first would
only add a `pre_reset_*` file beside the `post_restore_*` snapshots (the
`ls` glob above ignores it either way).

`--single-transaction` with `ON_ERROR_STOP=1` mirrors the atomic restore
contract of `global-teardown.ts`: any failure rolls back, leaving the empty
schema rather than a half-loaded database. Then sanity-check the result:

```bash
uv run python -m scripts.ops.restore_checks.check_django_orm
```

## File locations

- Scrubbed dump, consumer side: `restore/scrubbed_<instance-user>_<ts>.dump`
- Scrubbed dump, producer side on the production host: `<BASE_DIR>/restore/`
- Preserved private configuration: `restore/xeroapp.csv`, `restore/aiprovider.csv`
- Baseline snapshot: `backups/post_restore_<ts>.sql.gz`
- Seed log: `logs/seed_xero_output.log`

Keep the source dump and the baseline snapshot until the E2E suite has passed.
`restore/` also holds the E2E harness's own recovery artefacts, so never remove
it recursively — remove the named dump once the operator approves.
