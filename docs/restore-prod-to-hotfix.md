# Restore Production to the Hotfix Checkout

The hotfix checkout (`~/src/docketworks_hotfix`) is the MSM **hotfix
environment**: a second working copy whose database is refreshed by restoring
the production database into it, served on its own ngrok domain
(`docketworks-msm-hotfix.ngrok-free.app`), where the E2E suite runs to verify
production hotfixes without disturbing the main development environment.

This is NOT the anonymised dev/UAT refresh — that flow (scrub, reseed to a
demo Xero organisation) is
[`restore-prod-to-nonprod.md`](restore-prod-to-nonprod.md). A hotfix restore
keeps real production data, so the safety concern is different: the copy must
never **act on** production's external systems.

## Database role

This checkout connects as the **`dw_msm_prod`** role (`.env` `DB_USER`) —
deliberately identical to the owner recorded in every production dump. Role
parity is what lets production dumps restore **verbatim**, with no ownership
rewriting, and the application then operates as the table owner exactly as
production does. One-time setup (needs superuser):

```bash
sudo -u postgres psql \
  -c "CREATE ROLE dw_msm_prod LOGIN CREATEDB PASSWORD '<the .env DB_PASSWORD>';"
```

The databases are owned by this role, so re-restores (drop and recreate) need
no further superuser access.

## The load sequence

The load itself is the one in
[`restore-prod-to-nonprod.md`](restore-prod-to-nonprod.md): restore the dump
into a v1-shaped source database, reset and migrate the target, and load it
with `scripts/ops/migrate_v1_data.sh`. It differs here only in which checkout,
domain, and database it targets, plus the unscrubbed-specific repairs below.
Two of that runbook's steps change meaning against an unscrubbed dump:

- **The preserve/re-insert step does not apply.** The scrubbed dump strips
  `workflow_xeroapp` and `workflow_aiprovider`; an unscrubbed dump carries
  both, so production's rows — including live Xero token material and
  production's `redirect_uri` — arrive with the load. That is exactly why the
  repairs below are mandatory.
- **The sections from "Reconnect Xero" onward do not run.** They re-point the
  mirror at a demo organisation; the hotfix keeps production's mirror,
  read-only. Their prerequisite that `XERO_READONLY` be unset belongs to those
  sections only — here every process runs under it.

## Mandatory steps when restoring production into this checkout

1. **Back up the production database.** Take and retain a fresh backup of
   production as part of producing the copy being restored.

2. **Clear the Xero token** so this copy cannot call Xero with production's
   restored credentials:

   ```
   POST /api/xero/disconnect/
   ```

   (office-staff auth; the endpoint clears tokens on the active `XeroApp` and
   keeps the row, so re-authorising later needs no re-entered credentials).

3. **Repair the Xero redirect.** An unscrubbed restore carries production's
   `XeroApp.redirect_uri`, so the Xero login would send the browser back to
   production. Set it from this checkout's `APP_DOMAIN`:

   ```bash
   uv run python manage.py shell -c "
   from django.conf import settings
   from apps.xero.models import XeroApp
   app = XeroApp.objects.get(is_active=True)
   app.redirect_uri = f'https://{settings.APP_DOMAIN}/api/xero/oauth/callback/'
   app.save()
   print(app.redirect_uri)
   "
   ```

   The same URI must be registered in the Xero developer app:
   `https://docketworks-msm-hotfix.ngrok-free.app/api/xero/oauth/callback/`.

   Generated links need no equivalent repair: `migrate_v1_data.sh` excludes
   `django_site`, nothing reads the sites framework, and every absolute URL is
   built from this checkout's `APP_DOMAIN`, so production's domain never
   reaches the target database.

4. **Restore production-owned files referenced by the database.** The restore
   brings file **paths**, not files. Before testing anything that renders
   files, rsync the mutable production instance directories from
   `/opt/docketworks/instances/msm-prod/` into the storage roots this
   checkout's `.env` names:

   - `mediafiles/` → `MEDIA_ROOT`
   - `phone-recordings/` → `PHONE_RECORDING_STORAGE_ROOT`

   Those two roots are the whole file surface: session replays are database
   rows (`workflow_sessionreplayrecording` / `workflow_sessionreplaychunk`)
   and no setting names a disk root for them, so they arrive with the restore.
   The files are instance-user-owned on the server, so the remote rsync
   escalates via `sudo -iu dw_msm_prod`. The v1 helper that automated this
   (`pull_prod_files.sh`) is not ported — see
   [`v1-disposition.md`](v1-disposition.md);
   `scripts/ops/recreate_jobfiles.py` fabricates placeholders where real
   bytes are not needed.

   Keep the `.env` roots inside this checkout; **never** point them at another
   checkout. Verify representative DB-backed files — logos and phone
   recordings especially — before running E2E.

5. **Run every process with `XERO_READONLY=true`** so that even a reconnected
   Xero cannot write to MSM's real organisation. The flag is
   **process-scoped**: the Django server, the Celery worker, and Celery beat
   sharing this database must all carry it. Under the flag the sync worker
   skips whole runs, operator write commands refuse to run, and every
   suppressed write is logged.

6. **Leave the accounting provider as `xero`.** The read-only provider is
   selected by the process-level flag: `apps/accounting/registry.py` swaps the
   `xero` backend for `xero_readonly` whenever `settings.XERO_READONLY` is
   set, so real reads and auth keep working while writes return well-formed
   fakes and nothing reaches the tenant.
