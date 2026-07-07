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
   credentials. Either `POST /api/xero/disconnect` (office staff) in the app,
   or the shell equivalent of what that view does (`xero_disconnect` in
   `apps/workflow/views/xero/xero_view.py`):

   ```python
   from django.core.cache import cache
   from apps.workflow.api.xero.active_app import get_active_app, wipe_tokens_and_quota

   cache.delete("xero_tenant_id")
   wipe_tokens_and_quota(get_active_app())
   ```

3. **Point Xero OAuth back to the hotfix server.** A production restore keeps
   production's `XeroApp.redirect_uri`; if it is not repaired, Xero login will
   send the browser back to production instead of this checkout. Set the active
   app's redirect URI from `APP_DOMAIN`:

   ```python
   from django.conf import settings
   from apps.workflow.models import XeroApp

   expected = f"https://{settings.APP_DOMAIN}/api/xero/oauth/callback/"
   app = XeroApp.objects.get(is_active=True)
   app.redirect_uri = expected
   app.save(update_fields=["redirect_uri", "updated_at"])
   ```

   The same URI must be registered in the Xero developer app:
   `https://docketworks-msm-hotfix.ngrok-free.app/api/xero/oauth/callback/`.

4. **Run the hotfix processes with `XERO_READONLY=True`** so that even a
   reconnected Xero cannot write to MSM's real organisation. This is
   process-scoped: the Django server, Celery worker, and Celery beat sharing
   this database must all have `XERO_READONLY=True`.

5. **Set the accounting provider to Xero.** The read-only provider is selected
   by the process-level `XERO_READONLY=True` flag when the configured backend is
   `xero`:

   ```python
   from apps.workflow.models import CompanyDefaults

   defaults = CompanyDefaults.get_solo()
   defaults.accounting_provider = "xero"
   defaults.save()
   ```
