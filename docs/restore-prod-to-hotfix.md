# Restore Production to the Hotfix Checkout

This checkout (`~/src/docketworks_prod`) is the MSM **hotfix environment**: its
database is refreshed by restoring the production DB into it, it is served via
the `docketworks-msm-prod` ngrok domain, and the E2E suite runs here to verify
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

3. **Set the accounting provider to read-only Xero** so that even a
   reconnected Xero (e.g. for an E2E run) cannot write to MSM's real
   organisation:

   ```python
   from apps.workflow.models import CompanyDefaults

   defaults = CompanyDefaults.get_solo()
   defaults.accounting_provider = "xero_readonly"
   defaults.save()
   ```

   > `xero_readonly` is under construction (parallel session, 2026-07-07) —
   > until it lands in the provider registry
   > (`apps/workflow/accounting/xero/provider.py`), a cleared token is the only
   > guard against Xero writes, so step 2 is non-negotiable.
