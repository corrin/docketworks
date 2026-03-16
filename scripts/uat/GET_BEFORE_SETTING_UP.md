# What to Collect Before Setting Up a New Client

Checklist of everything you need from a client before creating their DocketWorks instance. Get all of this sorted before you start — it's much easier than going back and forth.

## From the Client

### Xero Access (Required)

You need access to their Xero organisation to configure payroll correctly.

**Ask the client to set up in Xero (or do it with them):**

- [ ] **Earnings Rates** (Payroll → Settings → Pay Items → Earnings):
  - Ordinary Time (1.0x)
  - Time and a Half (1.5x)
  - Double Time (2.0x)
  - Unpaid Time (0.0x)
- [ ] **Leave Types** (Payroll → Settings → Pay Items → Leave):
  - Annual Leave
  - Sick Leave
- [ ] **Payroll Calendar** (Payroll → Settings → Payroll Calendars):
  - Weekly, starting Monday
- [ ] **Employees** — each needs IRD number, bank account, tax code, leave balances
- [ ] **Shop Client contact** — a Xero contact named "[Company Name] Shop" for internal/non-billable work

### Company Details (Required)

- [ ] Company name and acronym (e.g. "Morris Sheetmetal", "MSM")
- [ ] Company address
- [ ] Company contact email and website
- [ ] Charge-out rate per hour (e.g. $105/hr)
- [ ] Base wage rate (e.g. $32/hr)
- [ ] Time markup percentage (e.g. 30%)
- [ ] Materials markup percentage (e.g. 20%)
- [ ] Annual leave loading percentage (e.g. 8%)
- [ ] Financial year start month
- [ ] Preferred starting job number and PO number
- [ ] PO prefix (e.g. "PO-" or "JO-")
- [ ] Standard working hours (e.g. Mon-Fri 07:00-15:00)

### Staff List (Required)

For each staff member:
- [ ] Email address (used as login)
- [ ] First name, last name, preferred name
- [ ] Wage rate
- [ ] Weekly hours pattern (Mon-Fri, Sat, Sun)
- [ ] Which Xero employee they correspond to

### SOPs and Documents (Optional)

If the client has standard operating procedures, safety documents, forms etc:
- [ ] Collect all `.doc`/`.docx` files
- [ ] Upload to a Google Shared Drive with this folder structure:
  - `01 - How we work` (policies, basics)
  - `02 - SOPs` (standard operating procedures)
  - `03 - Reference Library` (reference docs, forms, registers)
- [ ] Note the Shared Drive ID and each folder ID

### Google Sheets Quote Template (Optional)

If the client wants quote generation:
- [ ] Create a master quote template in Google Sheets
- [ ] Create a Google Drive folder for storing generated quotes
- [ ] Note the template ID and folder ID

### Supplier Integrations (Optional)

- [ ] **Steel & Tube** — username and password if they use S&T for materials

## You Set Up (Not From Client)

These are things you configure yourself — not things the client provides.

### Xero Developer App

For each client instance:
- [ ] Create app at https://developer.xero.com/app/manage
- [ ] Set redirect URI: `https://<instance>.docketworks.site/api/xero/oauth/callback/`
- [ ] Note Client ID and Client Secret
- [ ] Create webhook subscription, note the key

### Google Service Account

Shared across all instances (already done during base setup):
- [ ] Service account with Sheets + Drive APIs enabled
- [ ] JSON key file on server
- [ ] Share the client's Google Shared Drive with the service account email

### AI Provider (Optional)

If enabling AI features (quote extraction, chat):
- [ ] Configure via admin: provider name, API key, model name

## After Instance Creation

Once the instance is running, complete the setup:

```bash
# 1. Log into the app and connect Xero (OAuth flow in browser)

# 2. Configure Xero tenant
python manage.py xero --setup

# 3. Sync data from Xero (contacts, employees, etc.)
python manage.py start_xero_sync

# 4. Create internal shop jobs (leave, training, admin, etc.)
python manage.py create_shop_jobs

# 5. Link staff members to Xero employees
python manage.py xero --link-staff

# 6. Set Google folder IDs in CompanyDefaults via admin (if applicable)
```

## Quick Reference: What Goes Where

| Information | Where it ends up |
|------------|-----------------|
| Xero Client ID/Secret/Webhook Key | `credentials.env` |
| Company details, rates, markups | `CompanyDefaults` (fixture or admin) |
| Staff members | `Staff` model (fixture or admin) → linked to Xero |
| SOPs/documents | Google Shared Drive → imported via management command |
| Quote template | Google Sheets → ID stored in `CompanyDefaults` |
| Supplier credentials | `.env` file (Steel & Tube username/password) |
