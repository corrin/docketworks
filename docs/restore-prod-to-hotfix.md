# Restore Production to the Hotfix Checkout

This checkout (`~/src/docketworks_prod`) is the MSM **hotfix environment**: its
database is refreshed by restoring the production DB into it, it is served via
the `docketworks-msm-hotfix` ngrok domain, and the E2E suite runs here to verify
prod hotfixes.

This is NOT the anonymised dev/UAT restore — that flow (scrub, reseed to a dev
Xero org) is [restore-prod-to-nonprod.md](restore-prod-to-nonprod.md). A hotfix
restore keeps real production data; the safety concern is different: the copy
must never **act on** production's external systems.

## Mandatory steps when restoring production into this checkout

1. **Back up the production DB.** Take and retain a fresh backup of production
   as part of producing the copy being restored.

2. **Clear the Xero token** so this copy cannot call Xero with production's
   credentials. Use `POST /api/xero/disconnect` as office staff, or mirror
   `xero_disconnect` in `apps/workflow/views/xero/xero_view.py`.

3. **Point Django and Xero URLs back to the hotfix server.** A production
   restore keeps production's `django_site.domain` and `XeroApp.redirect_uri`;
   if they are not repaired, generated links and Xero login can send the browser
   back to production instead of this checkout. Set both from `APP_DOMAIN`.
   The same URI must be registered in the Xero developer app:
   `https://docketworks-msm-hotfix.ngrok-free.app/api/xero/oauth/callback/`.

4. **Restore production-owned files referenced by the DB.** The DB restore
   brings file paths, not the files. Copy the mutable production instance
   directories into this checkout before testing anything that renders files.
   This includes at least `mediafiles/`, `phone-recordings/`, and
   `session-replays/`.

   Source: `/opt/docketworks/instances/msm-prod/` on MSM. Targets:
   `MEDIA_ROOT=/home/corrin/src/docketworks_prod/mediafiles`,
   `PHONE_RECORDING_STORAGE_ROOT=/home/corrin/src/docketworks_prod/.local/phone-recordings`,
   and
   `SESSION_REPLAY_STORAGE_ROOT=/home/corrin/src/docketworks_prod/.local/session-replays`.
   Do not point any of these at `~/src/docketworks`. Verify representative
   DB-backed files, especially logos and phone recordings, before running E2E.

5. **Run the hotfix processes with `XERO_READONLY=True`** so that even a
   reconnected Xero cannot write to MSM's real organisation. This is
   process-scoped: the Django server, Celery worker, and Celery beat sharing
   this database must all have `XERO_READONLY=True`.

6. **Set the accounting provider to Xero.** The read-only provider is selected
   by the process-level `XERO_READONLY=True` flag when the configured backend is
   `xero`.
