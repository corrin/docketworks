# Xero Setup

DocketWorks requires a Xero subscription. The app focuses on jobs management and leaves Xero to
handle invoices, payroll, and accounting. The integration is tight — time spent on a job is
posted to Xero for payroll and added to the invoice.

## Step 1: Configure the Xero organisation

Log into Xero and verify (or create) the following. These are required regardless of whether this
is a dev, demo, or production setup.

### Earnings rates (Payroll → Settings → Pay Items → Earnings)

These must exist with **exact names** — sync pulls them into `XeroPayItem` rows and the code then
looks them up by name:

| Name | Rate multiplier |
|------|-----------------|
| Ordinary Time | 1.0x |
| Time and one half | 1.5x |
| Double Time | 2.0x |

"Ordinary Time" and "Time and one half" are pinned by exact name in
`apps/xero/models/xero_pay_item.py` (`get_ordinary_time`, `get_by_multiplier`), and every new job
defaults its pay item to "Ordinary Time" (`apps/job/models/job.py`) — a missing or misspelled
rate breaks job creation and payroll posting. The 2.0x rate is resolved by its multiplier rather
than by name, so "Double Time" is the required convention but not a code-enforced spelling.

The 1.5x name is "Time and one half" exactly — "Time and a Half" or any other spelling fails the
name lookups above. There is no 0.0x "Unpaid Time" earnings rate; unpaid time is the
"Unpaid Leave" leave type below.

### Leave types (Payroll → Settings → Pay Items → Leave)

- Annual Leave
- Sick Leave
- Unpaid Leave
- Bereavement Leave

Exact names again: the weekly timesheet payroll columns map "Annual Leave", "Sick Leave" and
"Bereavement Leave" by name (`apps/timesheet/services/weekly_timesheet_service.py`), and
"Unpaid Leave" is the one leave type created as unpaid — every other leave type is paid
(`apps/xero/payroll_setup.py`, `UNPAID_LEAVE_NAME`).

### Payroll calendar (Payroll → Settings → Payroll Calendars)

A weekly payroll calendar starting on **Monday**. The name must equal
`CompanyDefaults.xero_payroll_calendar_name` — the seeded dev/demo configuration uses
"Weekly Testing" (`scripts/server/templates/company-defaults.json.template`); production uses
whatever calendar name the client already runs. Payroll posting requires Monday-to-Sunday
periods, so `manage.py xero --setup` aborts when the calendar is anchored to any other day.

### Payroll must be provisioned (demo organisations)

A newly created demo organisation has the payroll product unprovisioned, and no API turns it on:
someone must open Payroll in the Xero web UI for that organisation once and complete the
activation prompt. Until then every NZ Payroll call answers `403 Forbidden` with an **empty
body** even though the token, tenant id header, and scopes are all correct. A `403` whose body
names the error — `{"Title":"Forbidden","Detail":"AuthenticationUnsuccessful"}` — is a different
failure: tenant drift, a valid token for an organisation that no longer exists. The full
diagnosis and repair sequence is in
[restore-prod-to-nonprod.md](restore-prod-to-nonprod.md#activate-payroll-in-the-xero-organisation).

## Step 2: Create the Xero developer app

The developer app is how Xero knows where to send this installation's data.

### Alternative: share an app through the webhook router

Xero allows **one webhook delivery URL and one signing key per app**, which is why every install
has needed its own app registration just to receive webhooks. For a low-value install — a trial, a
demo, or a dev machine — that registration is pure overhead.

[docketworks-webhook](https://github.com/corrin/docketworks-webhook) is a shared router at
`https://hooks.docketworks.site` that removes it. One Xero app points its single delivery URL at
the router; the router verifies the delivery, splits the batch by `tenantId`, re-signs each slice
with the destination install's own key, and forwards it. **Nothing in this repository changes** —
the install still receives at its own `/api/xero/webhook/` and still verifies the HMAC exactly as
`apps/xero/webhooks.py` does today.

Use it for trials, demos, dev machines and internal environments. Give a production client its own
app: an uncertified Xero app is capped on how many organisations may connect to it, so every trial
sharing the app spends that budget, and one shared registration is a single point of failure for
everything behind it.

Sharing an app means the install's `XeroApp` row carries the **shared** app's `client_id`,
`client_secret` and `webhook_key` rather than its own. Two things follow:

- The install's own OAuth callback URL must be added to the shared app's redirect URI list. The
  redirect URI is per install and exact-parity; only the credentials are shared. OAuth itself does
  not go through the router, because the callback carries an authorization code and the router is
  deliberately a lower-privacy service.
- Someone must add a route on the router keyed by this install's `CompanyDefaults.xero_tenant_id`.
  Until that route exists the router accepts and drops the events, and the hourly
  `xero_regular_sync_task` is what closes the gap. A demo organisation gets a new tenant id when it
  is recreated, so its route needs re-pointing on that cycle.

The router's README covers registering an app and adding a route. The rest of this page assumes a
dedicated app; where it says to create one, a shared app is the substitute.

1. Go to the [Xero Developer Portal](https://developer.xero.com/app/manage) and log in.
2. Click "New App".
   - Name: `Docketworks <instance>` (e.g. `Docketworks MSM` for a client instance,
     `docketworks-dave Development` for a dev machine)
   - Integration type: **Web app**
   - **OAuth 2.0 Redirect URI:** your domain + `/api/xero/oauth/callback/`
     (e.g. `https://docketworks-dave.ngrok-free.app/api/xero/oauth/callback/`). This URL is
     exact-parity: Xero holds it, and it must match the `redirect_uri` stored on the `XeroApp`
     row verbatim.
3. Copy the **Client ID** and **Client Secret**.
4. Under Webhooks, create a subscription. Skip this step entirely if the install is sharing an
   app through the webhook router — the shared app already has a delivery URL, and adding a
   second subscription is not possible.
   - **Webhook Delivery URL:** your domain + `/api/xero/webhook/`
     (e.g. `https://docketworks-dave.ngrok-free.app/api/xero/webhook/`) — also exact-parity,
     mounted in `config/urls.py`.
   - Copy the **Webhook signing key**. It is stored in `XeroApp.webhook_key`; a row with a NULL
     key cannot verify incoming webhooks (the verifier accepts a delivery if any active app's
     key produces a matching HMAC — see `apps/xero/models/xero_app.py`).

## Step 3: Store the credentials

The Client ID, Client Secret, and Webhook Key live in the database as a `XeroApp` row, never in
`.env`. How the row gets there depends on the environment:

- **Dev machine:** copy `apps/xero/fixtures/xero_apps.json.example` to
  `apps/xero/fixtures/xero_apps.json`, fill in the credentials, and
  `uv run python manage.py loaddata apps/xero/fixtures/xero_apps.json`. The walkthrough,
  including the shared team credentials and per-dev `label` convention, is in
  [initial_install.md](initial_install.md).
- **Server instance:** put `XERO_CLIENT_ID`, `XERO_CLIENT_SECRET`, `XERO_WEBHOOK_KEY`, and
  `XERO_REDIRECT_URI` in the root-owned
  `/opt/docketworks/config/<client>-<env>.credentials.env`.
  `scripts/server/instance.sh` renders them into the row via
  `scripts/server/templates/xero-apps.json.template` on `create` and `reconfigure`; the loader
  skips a row a restored database already carries.

## Demo organisation lifecycle

- **A Xero demo organisation expires roughly monthly, and recreating it
  gives the org a NEW tenant id.** The signature is every live Xero API call
  answering `403 {"Title":"Forbidden","Detail":"AuthenticationUnsuccessful"}`
  while everything that does not call Xero looks healthy: `/api/xero/ping/`
  reports `connected=True` and `get_valid_token()` returns a token with the
  right scopes and a future `expires_at` — the token is valid, just no
  longer for a tenant that exists. Diagnose by comparing
  `GET https://api.xero.com/connections` against
  `CompanyDefaults.xero_tenant_id`; a configured id absent from that list is
  the whole diagnosis. Repair in three steps: re-consent through
  `/api/xero/authenticate/` **on the ngrok domain** (Xero redirects to the
  registered callback, so the flow only completes when it is started
  there), point `CompanyDefaults.xero_tenant_id` at the live tenant, and
  clear `TENANT_ID_CACHE_KEY` (`apps/xero/auth.py`) so the next call
  re-resolves instead of serving the dead id from cache.
- **After a demo-org recreation the mirror tables still hold the dead org's
  entity ids**, so the next sync matches nothing and creates a second copy
  of every contact it "finds". The repair is the full
  [restore-prod-to-nonprod runbook](restore-prod-to-nonprod.md), which
  rebuilds the non-production database from production and re-points it at
  the current demo tenant; clearing individual duplicates by hand leaves
  the id mismatch that produced them.
- **`workflow_xeroapp` is the single source of truth for Xero token
  material.** Xero rotates the refresh token on every refresh, so any copy
  taken outside that row — a backup, an exported fixture, a note — is dead
  the moment the next refresh happens. Before a planned database wipe, copy
  the token columns (`token_type`, `access_token`, `refresh_token`,
  `expires_at`, `scope`) across the wipe and write them back afterwards;
  the E2E harness automates exactly that around its own restore
  (`frontend/tests/scripts/global-teardown.ts`). If another environment
  refreshed last, Xero answers `invalid_grant: Refresh token has been
  consumed` — copy the columns from whichever database refreshed most
  recently, or redo the OAuth consent.
