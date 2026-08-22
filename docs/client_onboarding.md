# Client Onboarding

Everything needed to take a new client from signed contract to running instance. This is the
handoff document for the onboarding specialist.

---

## Phase 1: Collect From Client

Get all of this before you start building anything.

### Company Details

- [ ] Company name and acronym (e.g. "Morris Sheetmetal", "MSM")
- [ ] Company logo (PNG, used in PDFs and the app) — both a square/compact logo and a wide
      letterhead version (see Phase 7h)
- [ ] Company address (street, suburb, city, postcode, country)
- [ ] Company email and website
- [ ] Standard working hours (e.g. Mon-Fri 07:00-15:00)
- [ ] Financial year start month (e.g. April)
- [ ] Preferred starting job number and PO number
- [ ] PO prefix (e.g. "PO-" or "JO-")

### Pricing & Rates

- [ ] Charge-out rate per hour (e.g. $105/hr)
- [ ] Base wage rate (e.g. $32/hr)
- [ ] Time markup percentage (e.g. 30%)
- [ ] Materials markup percentage (e.g. 20%)
- [ ] Annual leave loading percentage (e.g. 8%)

### Staff List

For each staff member:

- [ ] Email address (used as login)
- [ ] First name, last name, preferred name
- [ ] Wage rate
- [ ] Weekly hours pattern (Mon-Fri, Sat, Sun)
- [ ] Which Xero employee they correspond to (name must match)
- [ ] Profile photo (optional)

### SOPs and Documents (if applicable)

If the client has standard operating procedures, safety documents, forms, registers:

- [ ] Collect all `.doc`/`.docx` files
- [ ] These will be uploaded to a Google Shared Drive with this folder structure:
  - `01 - How we work` (policies, basics)
  - `02 - SOPs` (standard operating procedures)
  - `03 - Reference Library` (reference docs, forms, registers)

### Quote Template (if applicable)

If the client wants quote generation via Google Sheets:

- [ ] Get their existing quote format/template (or use the default)

### Supplier Integrations (if applicable)

- [ ] **Steel & Tube** credentials (username and password) if they use S&T for materials

---

## Phase 2: Xero

The client needs a Xero subscription. DocketWorks handles jobs and delegates invoicing, payroll,
and accounting to Xero.

### 2a. Client configures Xero (or you do it with them)

**Pay items and payroll calendar:** follow [xero_setup.md](xero_setup.md) Step 1. It carries the
exact earnings-rate and leave-type names the code matches on and the payroll-calendar naming rule
(`CompanyDefaults.xero_payroll_calendar_name` — the client's own calendar name in production).

**Employees** (Payroll > Employees):
- Each needs IRD number, bank account, tax code, and leave balances before payroll posting works.

**Shop Client** (Contacts > Add Contact):
- Create a contact named "[Company Name] Shop" (e.g., "Morris Sheetmetal Shop").
- Used for leave, admin time, training, etc. — this contact becomes the company that
  `CompanyDefaults.shop_company` points at, and every internal shop job hangs off it.

**Sales Branding Theme** (Settings > Invoice settings):
- Configure the client's required quote and invoice presentation.
- Enter the approved quote wording in Xero's **Terms (Quotes)** field.
- The selected theme is stored in `CompanyDefaults.xero_sales_branding_theme_id`; select the
  required live theme before production finalisation. `manage.py xero --setup` keeps a
  still-present theme or falls back to the organisation's first, which is acceptable only for
  demo seeding.
- Quote terms are **two fields kept in sync by hand**: `CompanyDefaults.xero_quote_terms` is
  what DocketWorks sends on API-created quotes, and Xero's own **Terms (Quotes)** field is what
  Xero applies to emergency quotes created directly in Xero. Whenever the wording changes,
  update both. The initial DocketWorks wording is generated from the company website's
  `/terms-of-trade` page; review it and replace it if the approved wording differs. The demo
  wording must contain the literal text "Terms of trade can be found" —
  `apps/accounting/tests/test_quote_pdf.py` asserts it against the native Xero quote PDF.

### 2b. You create the Xero Developer App

Follow [xero_setup.md](xero_setup.md) Steps 2 and 3, with the production specifics:

- Name: `Docketworks <client>` (e.g. `Docketworks MSM`)
- OAuth 2.0 Redirect URI: `https://<instance>.docketworks.site/api/xero/oauth/callback/`
- Webhook Delivery URL: `https://<instance>.docketworks.site/api/xero/webhook/`

The Client ID, Client Secret, and Webhook Key go into the instance's root-owned
`/opt/docketworks/config/<client>-<env>.credentials.env` (`XERO_CLIENT_ID`,
`XERO_CLIENT_SECRET`, `XERO_WEBHOOK_KEY`, `XERO_REDIRECT_URI`).

**Add the client's production identifiers to the code-level denylist** — a PR
adding the production org's tenant id to `PRODUCTION_XERO_TENANT_IDS`
and the production app's client id to `PRODUCTION_XERO_CLIENT_IDS`
in `config/settings.py`. `assert_not_production_target` and the operator
guards refuse only the tenants in that list, so until the PR merges the new
client's live organisation is unprotected from seed/repair tooling run on a
misconfigured non-production instance. The list is deliberately hardcoded
(a guard that can be misconfigured away is no guard), which makes this a
required onboarding step, not an environment setting.

---

## Phase 3: Google Cloud

All Google integrations run through a service account in the **docketworks** GCP project
(https://console.cloud.google.com). One service account per client. Today the service account is
consumed by the nightly backup uploads; the Drive-consuming features (Sheets quote generation,
the Google-Doc authoring toolchain behind the process app) are described in
[v1-disposition.md](v1-disposition.md), and the CompanyDefaults IDs below are collected now so
they are in place when those features are exercised.

### 3a. Create the Service Account

1. In the docketworks GCP project: IAM & Admin > Service Accounts > Create Service Account
2. Name: `docketworks-<client>` (e.g., `docketworks-msm`)
3. Skip optional permissions, click Done
4. Click into the new service account > Keys > Add Key > Create new key > JSON
5. Download the JSON key file
6. Copy it to the server and set `GCP_CREDENTIALS` in the root-owned credentials file to its
   path. `instance.sh` copies it to `<instance>/gcp-credentials.json`, after which the original
   can be deleted.

### 3b. Google Workspace Delegation (production clients with Workspace)

Allows the service account to act on behalf of users in the client's domain.

**You provide to the client's Workspace admin:**
- The service account's **Client ID** (numeric — on the service account details page)
- The required **OAuth scopes**:
  - `https://www.googleapis.com/auth/drive`
  - `https://www.googleapis.com/auth/documents`
  - `https://www.googleapis.com/auth/spreadsheets`

**The client's Workspace admin does:**
1. Google Admin Console (admin.google.com)
2. Security > Access and data control > API Controls > Domain-wide delegation
3. Add new > paste the Client ID and scopes
4. Authorize

### 3c. Drive Folder Access (clients without Workspace, or UAT)

Share the relevant Drive folder(s) with the service account's email address (e.g.,
`docketworks-msm@docketworks-xyz.iam.gserviceaccount.com`) as an **Editor**.

For backups, share a Shared Drive with the service account as **Content Manager**. Put that
Shared Drive ID in `BACKUP_GDRIVE_TEAM_DRIVE_ID` in the root-owned credentials file. If backups
should be anchored to a specific folder inside that Shared Drive, put that folder's ID in
`BACKUP_GDRIVE_ROOT_FOLDER_ID`. Nightly database and file backups upload under `dw_backups/`
(`scripts/backup_db.sh`, `scripts/backup_instance_files.sh`, via the per-instance rclone config
`instance.sh` writes).

### 3d. Google Shared Drive Setup (if client has SOPs/documents)

1. Create a Google Shared Drive for the client
2. Share it with the service account email as a Content Manager
3. Create the folder structure:
   - `01 - How we work`
   - `02 - SOPs`
   - `03 - Reference Library`
4. Upload the client's documents (collected in Phase 1)
5. Note the Shared Drive ID and each folder ID — they go into CompanyDefaults
   (`google_shared_drive_id`, `gdrive_how_we_work_folder_id`, `gdrive_sops_folder_id`,
   `gdrive_reference_library_folder_id`)

### 3e. Quote Template (if applicable)

1. Create a master quote template in Google Sheets (or copy the default)
2. Create a Google Drive folder for storing generated quotes
3. Share both with the service account email
4. Note the template ID/URL and quotes folder ID/URL — they go into CompanyDefaults
   (`master_quote_template_id`/`master_quote_template_url`, `gdrive_quotes_folder_id`/
   `gdrive_quotes_folder_url`)

### 3f. Google Maps API Key

Used for address validation (`apps/company/services/geocoding_service.py`). A single key is
shared across all instances.

1. In the docketworks GCP project: APIs & Services > Credentials
2. Create an API key (or reuse the existing shared one)
3. Restrict it to the **Address Validation API**
4. Put it in the instance's root-owned credentials file as `GOOGLE_MAPS_API_KEY`;
   `instance.sh` loads it onto the `IntegrationSettings` row (ADR 0053), and a superuser
   can change it later on Admin > Integrations. Nothing reads it from the environment.

---

## Phase 4: AI Providers

Used for quote price extraction and the chatbot. Supported provider types are Claude, Gemini,
Mistral, and OpenAI (`apps/ai/enums.py`); every AI call goes through `apps/ai`'s LiteLLM-backed
gateway. Keys are stored as `AIProvider` rows in the database, never in `.env`.

For each provider the client will use:

- [ ] **Provider name** (friendly label)
- [ ] **Provider type** (Claude / Gemini / Mistral / OpenAI)
- [ ] **Model name** (e.g. `gemini-flash-latest` for automatic Gemini upgrades)
- [ ] **API key**
- [ ] Whether it should be the **default** provider

### Where the API keys come from

| Provider | Where | Notes |
|----------|-------|-------|
| Anthropic (Claude) | https://console.anthropic.com > API Keys | Requires billing setup |
| Google (Gemini) | https://aistudio.google.com > Get API Key | Any Google account, no billing needed for free tier |
| Mistral | https://console.mistral.ai > API Keys | Requires billing setup |
| OpenAI | https://platform.openai.com > API Keys | Requires billing setup |

**DocketWorks creates the keys in its own accounts and factors the cost into the service fee.
The client never touches them.**

On a server instance the keys go into the root-owned credentials file (`ANTHROPIC_API_KEY`,
`GEMINI_API_KEY`, `MISTRAL_API_KEY`), and `instance.sh` renders them into `AIProvider` rows via
`scripts/server/templates/ai-providers.json.template`. On a dev machine use
`apps/ai/fixtures/ai_providers.json.example` as described in
[initial_install.md](initial_install.md).

---

## Phase 5: Email

Password resets and notifications need SMTP credentials. Collect them during onboarding:

- For UAT, one SMTP account is shared across all instances.
- For production, a per-client Gmail account with an **app password** (Google Account >
  Security > App passwords — not the account password), plus the "from" address.

The application does not yet consume SMTP settings — `config/settings.py` reads no `EMAIL_*`
variables, and password state is handled by the `password_needs_reset` login flow. When the
email feature lands, the production credentials belong in the root-owned credentials file
(`EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `DEFAULT_FROM_EMAIL`), loaded onto the
`IntegrationSettings` row like the other install-level credentials (ADR 0053).

---

## Phase 6: Create the Instance

Follow [server_setup.md](server_setup.md) Part C:

```bash
# Step 1: scaffold credentials and CompanyDefaults config
# (--seed selects the seeded CompanyDefaults template; omit for a prospect.
# Seeding is decided here — create/reconfigure take no --seed.)
sudo scripts/server/instance.sh prepare-config <client> prod [--seed]

# Step 2: fill in both root-owned configuration files
sudoedit /opt/docketworks/config/<client>-prod.credentials.env
sudoedit /opt/docketworks/config/<client>-prod.company-defaults.json

# Step 3: create the instance
sudo scripts/server/instance.sh create <client> prod --no-start

# Step 4 (fresh instances): create the first login interactively
sudo scripts/server/dw-run.sh <client>-prod python manage.py createsuperuser
```

The root-owned `company-defaults.json` is the durable tenant configuration — the company
details, rates, markups, and working hours collected in Phase 1 go there before `create`.

---

## Phase 7: In-App Configuration

Once the instance is running:

### 7a. Xero Connection

1. Sign in to the application **on the instance's domain** (the OAuth flow must start and
   finish on the domain whose callback is registered in the Xero developer portal).
2. In that signed-in browser, open `https://<domain>/api/xero/authenticate/` and authorize the
   client's Xero organisation.
3. In production, confirm the required live sales branding theme is the one configured (see
   Phase 2a).
4. Run:
   ```bash
   sudo scripts/server/dw-run.sh <client>-prod python manage.py finalize_instance_onboarding
   ```

Finalisation discovers the connected tenant, validates production Xero configuration without
creating remote objects, and enables automated sync only after every onboarding check succeeds.
Demo onboarding uses `--seed-xero`. (See also [server_setup.md](server_setup.md) Part C.1
Path B — instances restored from an existing database skip finalisation and follow
[restore-prod-to-nonprod.md](restore-prod-to-nonprod.md) instead.)

### 7b. Company Settings

Verify `CompanyDefaults` carries what Phase 1 collected (most of it arrives from the root-owned
`company-defaults.json` at create time):

- Company name, acronym, address, email, website
- Charge-out rate, wage rate, markups, leave loading
- Working hours
- Shop company (must be the Xero contact created in Phase 2a — `shop_company` is NOT NULL)
- Financial year start month
- Starting job/PO numbers and PO prefix
- Google Drive IDs (Shared Drive, How We Work, SOPs, Reference Library — Phase 3d)
- Quote template and quotes folder IDs (Phase 3e, if applicable)
- Xero sales branding theme (controls quote and invoice presentation)
- Xero quote terms (copy the approved wording exactly to both `xero_quote_terms` and Xero's
  **Terms (Quotes)** field; keep both in sync — Phase 2a)
- KPI thresholds (optional, can be tuned later)

### 7c. Create Shop Jobs

```bash
sudo scripts/server/dw-run.sh <client>-prod python manage.py create_shop_jobs
```

Creates nine jobs against the shop company, by these exact names: Annual Leave, Sick Leave,
Bereavement Leave, Travel, Training, Business Development, Office Admin, Worker Admin, and
Bench - busy work. The command is idempotent — re-running updates descriptions instead of
duplicating.

### 7d. Staff Setup

1. Create employees in Xero Payroll. The normal Xero sync creates or updates the linked
   `Staff` rows in Docketworks. Xero owns legal names, payroll email, employment dates and
   pay basis/rate; Docketworks owns office email, access, preferred name, photo,
   classification and roster.
2. A newly imported employee initially has the Xero payroll email as both email addresses
   and no usable password. Set their Docketworks password, and change `office_email` if they
   have a separate office address. Either address logs into the same account.
3. Set weekly hours (`hours_mon` through `hours_sun`) and upload a profile photo if wanted.
   A salaried employee's hourly costing rate is derived from the payroll terms synced from
   Xero (annual salary over the working pattern's average weekly hours); what the
   application refuses is costing their time before those terms have synced, or when the
   synced pattern carries no contracted hours.

### 7e. Link Leave Jobs to Xero

Every new job defaults its pay item to "Ordinary Time", so each leave job created in 7c must be
re-pointed by hand: set the job's **Xero Pay Item** (`Job.default_xero_pay_item`) to the
matching leave type — Annual Leave job to the Annual Leave pay item, and likewise for Sick
Leave and Bereavement Leave.

### 7f. AI Providers

The `AIProvider` rows are loaded at instance creation from the root-owned credentials file
(Phase 4). To change keys later, edit the credentials file and run
`sudo scripts/server/instance.sh reconfigure <client> prod` — the loaders skip rows that are
already configured, so brand-new providers load and existing rows are left alone. Exactly one
provider is marked default.

### 7g. Import Documents (if applicable)

The SOPs uploaded to the Shared Drive in Phase 3d are surfaced through the process app's
`Procedure` records. The bulk import command and the Google-Doc authoring toolchain that create
them are described in [v1-disposition.md](v1-disposition.md) (`import_dropbox_hs_documents` and
the `explore_google_drive.py` family).

### 7h. Logo

`CompanyDefaults` carries two image fields: `logo` and `logo_wide`. The wide/letterhead logo is
the one PDF generation uses — purchase orders
(`apps/purchasing/services/purchase_order_pdf_service.py`) and workshop sheets
(`apps/job/services/workshop_pdf_service.py`). Invoice and quote PDFs come from Xero itself and
take their presentation from the sales branding theme (Phase 2a). Upload both logos.

---

## Quick Reference: What Goes Where

| Information | Destination |
|------------|-------------|
| Xero Client ID / Secret / Webhook Key | root-owned `credentials.env` → `XeroApp` row |
| Phone provider URL / login / account code | root-owned `credentials.env` (`PHONE_PROVIDER_*`) → `IntegrationSettings` row |
| GCP service account JSON key path | root-owned `credentials.env` (`GCP_CREDENTIALS`) |
| Backup Shared Drive / folder IDs | root-owned `credentials.env` (`BACKUP_GDRIVE_TEAM_DRIVE_ID`, `BACKUP_GDRIVE_ROOT_FOLDER_ID`) |
| Google Maps API key | root-owned `credentials.env` (`GOOGLE_MAPS_API_KEY`) → `IntegrationSettings` row |
| Email SMTP credentials | root-owned `credentials.env` (when the email feature lands — Phase 5) |
| AI provider keys | root-owned `credentials.env` → `AIProvider` rows |
| Supplier credentials (Steel & Tube) | `quoting.SupplierCredential` rows in the database |
| Company details, rates, markups, hours | `CompanyDefaults` (root-owned `company-defaults.json`) |
| Google Drive folder IDs | `CompanyDefaults` |
| Staff members | `Staff` rows (imported from Xero by `finalize_instance_onboarding`) |
| SOPs, procedures, forms | `Procedure` records (import tooling: [v1-disposition.md](v1-disposition.md)) |
| Logo | `CompanyDefaults.logo` / `CompanyDefaults.logo_wide` |
