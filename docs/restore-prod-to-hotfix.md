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

3. **Point Django and Xero URLs back to the hotfix server.** A production
   restore keeps production's `django_site.domain` and `XeroApp.redirect_uri`;
   if they are not repaired, generated links and Xero login can send the browser
   back to production instead of this checkout. Set both from `APP_DOMAIN`:

   ```python
   from django.conf import settings
   from django.contrib.sites.models import Site
   from apps.workflow.models import XeroApp

   Site.objects.update(domain=settings.APP_DOMAIN)
   expected = f"https://{settings.APP_DOMAIN}/api/xero/oauth/callback/"
   XeroApp.objects.exclude(redirect_uri=expected).update(redirect_uri=expected)
   ```

   The same URI must be registered in the Xero developer app:
   `https://docketworks-msm-hotfix.ngrok-free.app/api/xero/oauth/callback/`.

4. **Restore tenant media files used by DB fields.** The DB restore only brings
   `CompanyDefaults.logo` and `logo_wide` paths, for example
   `company_logos/logo_regular_msm.png` and `company_logos/logo_wide_msm.jpg`.
   Copy the corresponding files into this checkout's media storage and verify
   the settings UI renders both logos.

5. **Run the hotfix processes with `XERO_READONLY=True`** so that even a
   reconnected Xero cannot write to MSM's real organisation. This is
   process-scoped: the Django server, Celery worker, and Celery beat sharing
   this database must all have `XERO_READONLY=True`.

6. **Set the accounting provider to Xero.** The read-only provider is selected
   by the process-level `XERO_READONLY=True` flag when the configured backend is
   `xero`:

   ```python
   from apps.workflow.models import CompanyDefaults

   defaults = CompanyDefaults.get_solo()
   defaults.accounting_provider = "xero"
   defaults.save()
   ```
