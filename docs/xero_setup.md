# Xero Setup Guide

DocketWorks requires a Xero subscription. The app focuses on jobs management and leaves Xero to handle invoices, payroll, etc. There is a tight integration between the two — time spent on a job is posted to Xero for payroll and added to the invoice.

## Step 1: Configure the Xero Organisation

Log into Xero and verify (or create) the following. These are required regardless of whether this is a dev, demo, or production setup.

### Earnings Rates (Payroll → Settings → Pay Items → Earnings)

These must exist with **exact names** (matched by `XeroPayItem.name` during sync):

| Name | Rate Multiplier |
|------|-----------------|
| Ordinary Time | 1.0x |
| Time and one half | 1.5x |
| Double Time | 2.0x |

### Leave Types (Payroll → Settings → Pay Items → Leave)

- Annual Leave
- Sick Leave
- Unpaid Leave
- Bereavement Leave

### Payroll Calendar (Payroll → Settings → Payroll Calendars)

A weekly payroll calendar starting on Monday. The name must match `xero_payroll_calendar_name` in CompanyDefaults (default: "Weekly Testing" for dev/demo, or whatever the client uses in production).

## Step 2: Create the Xero Developer App

You need to create an app in Xero because we need to tell Xero where do send your Xero data to.

1. Go to the [Xero Developer Portal](https://developer.xero.com/) and log in.
2. Click "New App".
   - Name: e.g., `docketworks-dave Development`
   - Type: "Web app"
   - **OAuth 2.0 Redirect URI:** Your domain + `/api/xero/oauth/callback/` (e.g., `https://docketworks-dave.ngrok-free.app/api/xero/oauth/callback/`)
3. Copy the **Client ID** and **Client Secret**.
4. Under Webhooks, create a subscription:
   - **Webhook Delivery URL:** Your domain + `/api/xero/webhook/` (e.g., `https://docketworks-dave.ngrok-free.app/api/xero/webhook/`)
   - Copy the **Webhook Key**.
5. Paste the Client ID, Client Secret, and Webhook Key into the XeroApp row — either via `apps/workflow/fixtures/xero_apps.json` (loaded by `manage.py loaddata` during install) or via Admin → Xero Apps after the instance is up.
