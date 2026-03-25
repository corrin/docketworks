# Xero Setup Guide

DocketWorks requires you to have a Xero subscripton.  The app focuses on jobs management, and leaves Xero to handle invoices, payroll, etc. There is a very tight integration between the two, for example time spent on a job is posted to Xero for payroll, and added to the invoice.

This file documents how to set up Xero to work with DocketWorks.

## Step 1: Configure Xero

Log into Xero and configure all of the following before connecting the app.

### Earnings Rates (Payroll → Settings → Pay Items → Earnings)

Create these earnings rates with **exact names**:

| Name | Rate Multiplier |
|------|-----------------|
| Ordinary Time | 1.0x |
| Time and a Half | 1.5x |
| Double Time | 2.0x |
| Unpaid Time | 0.0x |

### Leave Types (Payroll → Settings → Pay Items → Leave)

Create these leave types:
- Annual Leave
- Sick Leave

### Payroll Calendar (Payroll → Settings → Payroll Calendars)

Create a weekly payroll calendar starting on Monday.

### Employees (Payroll → Employees)

For each employee, ensure they have:
- IRD number (9-digit tax ID)
- Bank account
- Tax code (e.g., 'M' for main employment)
- Leave balances configured

### Shop Client (Contacts → Add Contact)

Create a contact for internal work:
- Name: "[Your Company] Shop" (e.g., "Morris Sheetmetal Shop")

This will be used for leave, admin time, training, etc.

## Step 2: Link App and Xero

1. Open the app in your browser
2. Go to Admin → Xero
3. Click "Login with Xero"
4. Log into Xero and authorize the app
5. Run:

```bash
python manage.py xero --setup
python manage.py start_xero_sync
```

This pulls clients, accounts, pay items, stock, and employees from Xero into the app.

NB: If you have a backup from production, do NOT run start_xero_sync. Instead follow backup-restore-process.md to seed Xero with your backup.

## Step 3: Create Shop Jobs

1. Go to Admin → Settings
2. Set **Shop Client Name** to the shop contact you created in Xero
3. Run:

```bash
python manage.py create_shop_jobs
```

This creates: Annual Leave, Sick Leave, Bereavement Leave, Travel, Training, Business Development, Office Admin, Worker Admin, Bench.

## Step 4: Link Staff to Xero Employees

For each staff member who needs timesheets posted to Xero:

1. Go to Staff in the app (Admin > Staff)
2. Edit the staff member
3. Set their **Xero Employee ID** (dropdown of synced employees)
4. Ensure their wage rate is set (must be > $0)

## Step 5: Link Leave Jobs to Xero Leave Types

For leave to be posted correctly:

1. Find the Annual Leave job
2. Edit it and set **Xero Pay Item** to your Annual Leave type
3. Repeat for Sick Leave and any other leave types

## What Gets Synced

**Accounting (automatic after connection):**
- Clients ↔ Xero Contacts
- Invoices ↔ Xero Invoices
- Stock items ↔ Xero Items
- Chart of accounts, bills, quotes, purchase orders

**Payroll (after setup above):**
- Timesheets → Xero Timesheets
- Leave → Xero Leave Applications
