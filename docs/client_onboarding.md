# Client Onboarding

Everything needed to take a new client from signed contract to running instance. This is the handoff document for the onboarding specialist.

---

## Phase 1: Collect From Client

Get all of this before you start building anything.

### Company Details

- [ ] Company name and acronym (e.g. "Morris Sheetmetal", "MSM")
- [ ] Company logo (PNG, used in PDFs and the app)
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

The client needs a Xero subscription. DocketWorks handles jobs and delegates invoicing, payroll, and accounting to Xero.

### 2a. Client configures Xero (or you do it with them)

**Earnings Rates** (Payroll > Settings > Pay Items > Earnings):

| Name | Rate Multiplier |
|------|-----------------|
| Ordinary Time | 1.0x |
| Time and a Half | 1.5x |
| Double Time | 2.0x |
| Unpaid Time | 0.0x |

**Leave Types** (Payroll > Settings > Pay Items > Leave):
- Annual Leave
- Sick Leave

**Payroll Calendar** (Payroll > Settings > Payroll Calendars):
- Create a weekly payroll calendar starting on Monday

**Employees** (Payroll > Employees):
- Each needs IRD number, bank account, tax code, leave balances

**Shop Client** (Contacts > Add Contact):
- Create a contact named "[Company Name] Shop" (e.g., "Morris Sheetmetal Shop")
- Used for leave, admin time, training, etc.

### 2b. You create the Xero Developer App

1. Go to https://developer.xero.com/app/manage
2. Click "New App"
3. Name: `DocketWorks - [Client Name]`
4. Integration type: Web app
5. OAuth 2.0 Redirect URI: `https://<instance>.docketworks.site/api/xero/oauth/callback/`
6. Create the app, copy **Client ID** and **Client Secret**
7. Under Webhooks, create a subscription, copy the **Webhook Key**

These go into the instance's `credentials.env`.

---

## Phase 3: Google Cloud

All Google integrations run through a service account in the **docketworks** GCP project (https://console.cloud.google.com). One service account per client.

### 3a. Create the Service Account

1. In the docketworks GCP project: IAM & Admin > Service Accounts > Create Service Account
2. Name: `docketworks-<client>` (e.g., `docketworks-msm`)
3. Skip optional permissions, click Done
4. Click into the new service account > Keys > Add Key > Create new key > JSON
5. Download the JSON key file
6. Copy it to the server, set `GCP_CREDENTIALS` in the instance `.env`

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

Share the relevant Drive folder(s) with the service account's email address (e.g., `docketworks-msm@docketworks-xyz.iam.gserviceaccount.com`) as an Editor.

### 3d. Google Shared Drive Setup (if client has SOPs/documents)

1. Create a Google Shared Drive for the client
2. Share it with the service account email as a Content Manager
3. Create the folder structure:
   - `01 - How we work`
   - `02 - SOPs`
   - `03 - Reference Library`
4. Upload the client's documents (collected in Phase 1)
5. Note the Shared Drive ID and each folder ID — these go into CompanyDefaults

### 3e. Quote Template (if applicable)

1. Create a master quote template in Google Sheets (or copy the default)
2. Create a Google Drive folder for storing generated quotes
3. Share both with the service account email
4. Note the template ID and quotes folder ID — these go into CompanyDefaults

### 3f. Google Maps API Key

Used for address validation. This can be a single key shared across all instances.

1. In the docketworks GCP project: APIs & Services > Credentials
2. Create an API key (or reuse the existing shared one)
3. Restrict it to the **Address Validation API**
4. Set `GOOGLE_MAPS_API_KEY` in `.env` (or `shared.env` for UAT)

---

## Phase 4: AI Providers

Used for quote price extraction and the chatbot. Supports Google (Gemini), Anthropic (Claude), OpenAI, and Mistral. AI providers are configured **in the app** (Admin > AI Providers), not in `.env`.

For each provider the client wants to use:

- [ ] **Provider name** (friendly label)
- [ ] **Provider type** (Gemini / Claude / OpenAI / Mistral)
- [ ] **Model name** (e.g. `gemini-2.5-flash-lite-preview-06-17`)
- [ ] **API key**
- [ ] Whether it should be the **default** provider

### Where to get API keys

| Provider | Where | Notes |
|----------|-------|-------|
| Google (Gemini) | https://aistudio.google.com > Get API Key | Any Google account, no billing needed for free tier |
| Anthropic (Claude) | https://console.anthropic.com > API Keys | Requires billing setup |
| OpenAI | https://platform.openai.com > API Keys | Requires billing setup |
| Mistral | https://console.mistral.ai > API Keys | Requires billing setup |

**Recommended approach:** You create the keys in a docketworks account and factor the cost into the service fee. The client doesn't need to touch any of this.

---

## Phase 5: Email

Password resets and notifications require SMTP credentials.

For UAT, this is shared across all instances via `shared.env` (set up during base server setup).

For production, set in the instance `.env`:
- `EMAIL_HOST_USER` — Gmail address
- `EMAIL_HOST_PASSWORD` — Gmail app password (Google Account > Security > App passwords, not the account password)
- `DEFAULT_FROM_EMAIL` — the "from" address

---

## Phase 6: Create the Instance

Follow `uat_setup.md` (Part C) or the production deployment process.

```bash
# UAT
sudo scripts/uat/uat-instance.sh create <name>
# Fill credentials.env with Xero values
sudo scripts/uat/uat-instance.sh create <name>  # re-run to build
```

---

## Phase 7: In-App Configuration

Once the instance is running:

### 7a. Xero Connection

1. Log into the app as admin
2. Admin > Xero > "Login with Xero"
3. Authorize the client's Xero organisation
4. Run:
   ```bash
   python manage.py xero --setup
   python manage.py start_xero_sync
   ```

### 7b. Company Settings

In Admin > Settings, configure:
- Company name, acronym, address, email, website
- Charge-out rate, wage rate, markups, leave loading
- Working hours
- Shop client name (must match the Xero contact created in Phase 2a)
- Financial year start month
- Starting job/PO numbers and PO prefix
- Google Drive folder IDs (Shared Drive, How We Work, SOPs, Reference Library)
- Quote template ID and quotes folder ID (if applicable)
- KPI thresholds (optional, can be tuned later)

### 7c. Create Shop Jobs

```bash
python manage.py create_shop_jobs
```

Creates: Annual Leave, Sick Leave, Bereavement Leave, Travel, Training, Business Development, Office Admin, Worker Admin, Bench.

### 7d. Staff Setup

1. Create each staff member in Admin > Staff (or load from fixture)
2. Link each to their Xero employee:
   ```bash
   python manage.py xero --link-staff
   ```
   Or manually: Admin > Staff > edit > set Xero Employee ID
3. Set wage rates and weekly hours
4. Upload profile photos (optional)

### 7e. Link Leave Jobs to Xero

- Edit the Annual Leave job > set **Xero Pay Item** to the Annual Leave type
- Repeat for Sick Leave and any other leave types

### 7f. AI Providers (if applicable)

Admin > AI Providers > Add:
- Set provider type, model name, API key
- Mark one as default

### 7g. Import Documents (if applicable)

If SOPs/documents were uploaded to Google Drive in Phase 3d:

```bash
python manage.py import_dropbox_hs_documents
```

### 7h. Logo

Currently the logo file needs to be placed at `jobs_manager/logo_msm.png` in the codebase. This is hardcoded and will need to be made client-configurable in future.

---

## Quick Reference: What Goes Where

| Information | Destination |
|------------|-------------|
| Xero Client ID / Secret / Webhook Key | `credentials.env` |
| GCP service account JSON key path | `.env` (`GCP_CREDENTIALS`) |
| Google Maps API key | `.env` or `shared.env` (`GOOGLE_MAPS_API_KEY`) |
| Email SMTP credentials | `.env` or `shared.env` |
| Supplier credentials (Steel & Tube) | `.env` |
| Company details, rates, markups, hours | CompanyDefaults (Admin > Settings) |
| Google Drive folder IDs | CompanyDefaults (Admin > Settings) |
| AI provider keys | AIProvider model (Admin > AI Providers) |
| Staff members | Staff model (Admin > Staff) |
| SOPs, procedures, forms | Imported via management command |
| Logo | `jobs_manager/logo_msm.png` (hardcoded — needs fix) |
